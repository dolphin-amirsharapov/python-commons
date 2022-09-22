from __future__ import annotations
import contextlib
import time
from abc import ABC
from typing import Optional, Callable, TypeVar, Iterable

import requests
from requests import Response, Session

from commons.logging import log_info
from commons.rest_api.http_exceptions import BadGatewayException
from commons.threads import ThreadWrapper, start_threads, join_threads

_T = TypeVar('_T')


class BoilerplateFunctionsMixin(ABC):

    def make_get_function(self, http_client: HttpRestClient, session: Session):
        def _func():
            url = http_client.make_url()
            return session.get(url)

        return _func

    def make_get_by_id_function(self, http_client: HttpRestClient, session: Session, id_: int):
        def _func():
            url = http_client.make_url(id_)
            return session.get(url)

        return _func

    def make_post_function(self, http_client: HttpRestClient, session: Session, json: dict):
        def _func():
            url = http_client.make_url()
            return session.post(url, json=json)

        return _func

    def make_put_function(self, http_client: HttpRestClient, session: Session, json: dict):
        def _func():
            url = http_client.make_url(json['id'])
            return session.put(url, json=json)

        return _func

    def make_delete_function(self, http_client: HttpRestClient, session: Session, id_: int):
        def _func():
            url = http_client.make_url(id_)
            return session.delete(url)

        return _func


class HttpRestClient(BoilerplateFunctionsMixin):
    def __init__(
            self,
            base_url: str = None,
            base_params: dict = None,
            base_headers: dict = None,
            proxies: dict = None,
            *,
            bearer_token: str = None,
            base_retry_count: int = 3,
            base_retry_delay: int = 1,
    ):
        self.base_url = base_url
        self.base_params = base_params or {}
        self.base_headers = base_headers or {}
        self.proxies = proxies or {}
        self.bearer_token = bearer_token
        self.base_retry_count = base_retry_count
        self.base_retry_delay = base_retry_delay

    def execute(
            self,
            executable: Callable[[], requests.Response],
            *,
            retry_count: int = None,
            retry_delay: int = None,
    ) -> requests.Response:
        retry_count = retry_count or self.base_retry_count
        retry_delay = retry_delay or self.base_retry_delay

        for i in range(retry_count):
            try:
                response = executable()
                response.raise_for_status()
                return response

            except Exception as e:
                if i == retry_count - 1:
                    raise e
                time.sleep(retry_delay * (i + 1))

    def execute_in_thread_pool(
            self,
            funcs: Iterable[Callable[[], Response]],
            *,
            retry_count: int = 3,
            max_threads: int = 25
    ) -> requests.Response:
        threads = []

        for func in funcs:
            def _func():
                return self.execute(func, retry_count=retry_count)

            t = ThreadWrapper(target=_func)
            threads.append(t)

        start_threads(threads, max_threads=max_threads)
        join_threads(threads)

        for t in threads:
            yield t.result

    def make_url(self, append_suffix: str | int = None):
        url = self.base_url

        if not url:
            raise ValueError('base_url is not set')

        if append_suffix:
            if not isinstance(append_suffix, str):
                append_suffix = str(append_suffix)
            if not append_suffix.startswith('/'):
                append_suffix = '/' + append_suffix
            url += append_suffix

        return url

    @contextlib.contextmanager
    def make_session_ctx(self, headers: dict = None, params: dict = None):
        session = self.make_session(headers=headers, params=params)
        yield session
        session.close()

    def make_session(self, headers: dict = None, params: dict = None):
        sess = requests.Session()

        sess.headers.update(self.base_headers)
        sess.headers.update(headers or {})

        if self.bearer_token:
            sess.headers['Authorization'] = f'Bearer {self.bearer_token}'

        sess.params.update(self.base_params)
        sess.params.update(params or {})

        sess.proxies.update(self.proxies or {})

        return sess