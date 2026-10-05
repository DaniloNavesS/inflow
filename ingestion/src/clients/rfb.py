import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("inflow_ingestor")

DAV = "{DAV:}"
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
CHUNK_SIZE = 8 * 1024 * 1024


def get_rfb_session(token: str) -> requests.Session:
    """Sessão para o compartilhamento WebDAV público da RFB: o token é o usuário, sem senha."""
    session = requests.Session()
    session.auth = (token, "")
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=None,  # inclui PROPFIND
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_propfind(xml_text: str) -> dict[str, int | None]:
    """Converte a resposta PROPFIND em {nome: tamanho}; pastas terminam em '/' e não têm tamanho."""
    entries = {}
    root = ET.fromstring(xml_text)
    for response in root.iter(f"{DAV}response"):
        href = unquote(response.findtext(f"{DAV}href") or "")
        is_dir = href.endswith("/")
        name = href.rstrip("/").rsplit("/", 1)[-1]
        size = response.findtext(f".//{DAV}getcontentlength")
        entries[name + ("/" if is_dir else "")] = int(size) if size else None
    return entries


def list_folder(session: requests.Session, url: str) -> dict[str, int | None]:
    resp = session.request("PROPFIND", url.rstrip("/") + "/", headers={"Depth": "1"}, timeout=120)
    if resp.status_code == 401:
        raise RuntimeError(
            "RFB recusou o token de compartilhamento (HTTP 401). Atualize RFB_CNPJ_TOKEN no .env."
        )
    resp.raise_for_status()
    entries = parse_propfind(resp.text)
    # A primeira entrada é a própria pasta consultada.
    folder_name = url.rstrip("/").rsplit("/", 1)[-1] + "/"
    entries.pop(folder_name, None)
    return entries


def list_months(session: requests.Session, base_url: str) -> list[str]:
    entries = list_folder(session, base_url)
    return sorted(
        name.rstrip("/") for name in entries if name.endswith("/") and MONTH_PATTERN.match(name.rstrip("/"))
    )


def download_file(session: requests.Session, url: str, dest: Path, expected_size: int | None) -> Path:
    """Baixa para dest, retomando um .part interrompido; pula se o arquivo completo já está em cache."""
    if dest.exists() and expected_size is not None and dest.stat().st_size == expected_size:
        logger.info("RFB: %s já está em cache.", dest.name)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if expected_size is not None and offset > expected_size:
        partial.unlink()
        offset = 0

    headers = {"Range": f"bytes={offset}-"} if offset else {}
    logger.info("RFB: baixando %s (%s MB)%s", dest.name,
                round(expected_size / 1e6) if expected_size else "?",
                f", retomando em {offset / 1e6:.0f} MB" if offset else "")

    with session.get(url, headers=headers, stream=True, timeout=300) as resp:
        if resp.status_code == 416 and expected_size is not None and offset == expected_size:
            pass  # .part já estava completo
        else:
            resp.raise_for_status()
            mode = "ab" if resp.status_code == 206 else "wb"
            with open(partial, mode) as out:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    out.write(chunk)

    size = partial.stat().st_size
    if expected_size is not None and size != expected_size:
        raise RuntimeError(
            f"Download incompleto de {dest.name}: {size} de {expected_size} bytes. "
            "Execute novamente para retomar."
        )
    partial.replace(dest)
    return dest
