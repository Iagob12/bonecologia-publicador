"""Envia para o YouTube, pelo GitHub Actions, os Shorts que ficaram pendentes (ex.: limite diário de envios do canal).

Lê agenda_yt.json: [{"id", "idioma", "quando" (ISO), "video" (caminho no repo público bonecologia-midia), "titulo", "descricao", "tags", "status"}].
Pendente com horário futuro sobe privado com publishAt (o YouTube publica sozinho na hora); se a hora já passou (até 24 h), sobe público.
Credenciais nos segredos YT_PT / YT_EN (JSON de usuário autorizado do Google), nunca no repositório.
"""
import datetime as dt, json, os, sys
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

AGENDA = "agenda_yt.json"
MIDIA = "https://raw.githubusercontent.com/Iagob12/bonecologia-midia/main/"


def cliente(idioma):
    bruto = os.environ.get("YT_PT" if idioma == "pt" else "YT_EN")
    if not bruto: return None
    cred = Credentials.from_authorized_user_info(json.loads(bruto))
    if not cred.valid: cred.refresh(Request())
    return build("youtube", "v3", credentials=cred, cache_discovery=False)


def baixar(caminho):
    os.makedirs("_v", exist_ok=True)
    destino = os.path.join("_v", os.path.basename(caminho))
    with requests.get(MIDIA + caminho, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for bloco in r.iter_content(1 << 20): f.write(bloco)
    return destino


def enviar(yt, it, publicar_em):
    status = {"privacyStatus": "private" if publicar_em else "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publicar_em: status["publishAt"] = publicar_em
    corpo = {"snippet": {"title": it["titulo"][:100], "description": it["descricao"][:4900], "tags": it.get("tags", [])[:15], "categoryId": "27",
                         "defaultLanguage": it["idioma"], "defaultAudioLanguage": "pt-BR" if it["idioma"] == "pt" else "en"}, "status": status}
    req = yt.videos().insert(part="snippet,status", body=corpo, media_body=MediaFileUpload(baixar(it["video"]), chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None: _, resp = req.next_chunk()
    return resp["id"]


def main():
    agenda = json.load(open(AGENDA, encoding="utf-8")) if os.path.exists(AGENDA) else []
    agora = dt.datetime.now(dt.timezone.utc)
    travado, clientes, mudou = set(), {}, False
    for it in sorted(agenda, key=lambda x: x["quando"]):
        if it.get("status") != "pendente" or it["idioma"] in travado: continue
        quando = dt.datetime.fromisoformat(it["quando"]).astimezone(dt.timezone.utc)
        if (agora - quando).total_seconds() > 24 * 3600:
            it["status"] = "atrasado"; mudou = True; continue
        if it["idioma"] not in clientes: clientes[it["idioma"]] = cliente(it["idioma"])
        yt = clientes[it["idioma"]]
        if yt is None: continue
        futuro = (quando - agora).total_seconds() > 900
        try:
            vid = enviar(yt, it, quando.strftime("%Y-%m-%dT%H:%M:%SZ") if futuro else None)
            it.update(status="agendado" if futuro else "publicado", yt_id=vid, em=agora.isoformat()); it.pop("erro", None)
            print(f"youtube {it['status']}: {it['id']} -> {vid}")
        except Exception as e:
            it["erro"] = str(e)[:300]; it["erro_em"] = agora.isoformat()
            if "uploadLimitExceeded" in str(e) or "quotaExceeded" in str(e):
                travado.add(it["idioma"]); print(f"limite do YouTube ({it['idioma']}): tenta de novo na próxima rodada")
            else:
                it["tentativas"] = it.get("tentativas", 0) + 1
                if it["tentativas"] >= 3: it["status"] = "erro"
                print(f"erro em {it['id']}: {it['erro']}", file=sys.stderr)
        mudou = True
    if mudou: json.dump(agenda, open(AGENDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("youtube: nada pendente" if not mudou else "agenda_yt atualizada")


if __name__ == "__main__":
    main()
