import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import REQUEST_HEADERS


class SenateTLSAdapter(HTTPAdapter):
    """
    Adapter customizado para garantir compatibilidade TLS 1.2 com os servidores

    e firewalls do Senado Federal, evitando timeouts de negociação TLS 1.3 do OpenSSL 3.
    """

    def init_poolmanager(self, *args, **kwargs):

        ctx = ssl.create_default_context()

        ctx.maximum_version = ssl.TLSVersion.TLSv1_2

        kwargs["ssl_context"] = ctx

        return super().init_poolmanager(*args, **kwargs)


def get_resilient_session() -> requests.Session:

    session = requests.Session()

    session.headers.update(REQUEST_HEADERS)

    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )

    adapter = SenateTLSAdapter(
        max_retries=retries, pool_connections=10, pool_maxsize=10
    )

    session.mount("https://", adapter)

    session.mount("http://", adapter)

    return session
