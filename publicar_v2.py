"""Publicador v2 (GitHub Actions, sem o PC): Instagram, Facebook e TikTok, para todas as marcas.

agenda_v2.json: [{"id", "base", "unidade", "rede": "instagram"|"facebook"|"tiktok", "quando" (ISO UTC),
                  "video": "v/<base>.mp4" (no repo público bonecologia-midia), "legenda", "status"}]
Publica o que venceu (até 6 h de atraso; depois disso marca "atrasado"). Cada item é independente: se uma rede falha,
as outras seguem. Depois de 3 falhas o item vira "erro".

Segredos (nunca no repositório):
  META_UNIDADES  {"U01_BR_PSICO": {"page_id","page_token","ig_user_id","ig_token"}, ...}
  TIKTOK_APP     {"client_key","client_secret"}
  TIKTOK_TOKENS  {"U01_BR_PSICO": "<refresh_token>", ...}
  TIKTOK_MODO    "rascunho" (padrão: vai para a caixa de entrada do TikTok, você toca em Postar)
                 ou "publico" (depois da auditoria do app: posta direto)
"""
import datetime as dt, json, os, sys, time
import requests

G = "https://graph.facebook.com/v27.0"
TT = "https://open.tiktokapis.com/v2"
MIDIA = "https://raw.githubusercontent.com/Iagob12/bonecologia-midia/main/"
AGENDA = "agenda_v2.json"
ATRASO_MAX = 6 * 3600
ANTECEDENCIA = 180  # publica até 3 min antes da hora (o disparo pode chegar um pouco cedo)


def ok(r):
    if r.status_code >= 400: raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return r.json()


def env_json(nome):
    bruto = os.environ.get(nome, "").strip()
    return json.loads(bruto) if bruto else {}


# ---------------- Instagram (video_url) ----------------
def instagram(cfg, it):
    tok, uid = cfg["ig_token"], cfg["ig_user_id"]
    c = ok(requests.post(f"{G}/{uid}/media", data={"media_type": "REELS", "video_url": MIDIA + it["video"], "caption": it["legenda"][:2200],
                                                    "share_to_feed": "true", "access_token": tok}))
    for _ in range(80):
        st = ok(requests.get(f"{G}/{c['id']}", params={"fields": "status_code,status", "access_token": tok}))
        if st.get("status_code") == "FINISHED": break
        if st.get("status_code") == "ERROR": raise RuntimeError(f"Instagram recusou: {st}")
        time.sleep(15)
    else:
        raise RuntimeError("Instagram não processou em 20 min")
    return ok(requests.post(f"{G}/{uid}/media_publish", data={"creation_id": c["id"], "access_token": tok}))["id"]


# ---------------- Facebook Reels (file_url) ----------------
def facebook(cfg, it):
    tok, pg = cfg["page_token"], cfg["page_id"]
    ini = ok(requests.post(f"{G}/{pg}/video_reels", data={"upload_phase": "start", "access_token": tok}))
    vid = ini["video_id"]
    up = requests.post(f"https://rupload.facebook.com/video-upload/v27.0/{vid}",
                       headers={"Authorization": f"OAuth {tok}", "file_url": MIDIA + it["video"]})
    if up.status_code >= 400: raise RuntimeError(f"upload do Facebook: {up.status_code} {up.text[:200]}")
    ok(requests.post(f"{G}/{pg}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                    "description": it["legenda"][:2200], "access_token": tok}))
    return vid


# ---------------- TikTok (FILE_UPLOAD) ----------------
def tiktok_token(app, refresh):
    r = requests.post(f"{TT}/oauth/token/", data={"client_key": app["client_key"], "client_secret": app["client_secret"],
                                                   "grant_type": "refresh_token", "refresh_token": refresh}).json()
    if "access_token" not in r: raise RuntimeError("TikTok recusou renovar o acesso (entre de novo pelo tiktok_conectar.bat)")
    return r["access_token"]


def tiktok(app, refresh, it, modo):
    h = {"Authorization": f"Bearer {tiktok_token(app, refresh)}", "Content-Type": "application/json; charset=UTF-8"}
    dados = requests.get(MIDIA + it["video"], timeout=300).content
    tam = len(dados)
    fonte = {"source": "FILE_UPLOAD", "video_size": tam, "chunk_size": tam, "total_chunk_count": 1}
    if modo == "publico":
        corpo = {"post_info": {"title": it["legenda"][:2200], "privacy_level": "PUBLIC_TO_EVERYONE", "disable_duet": False,
                               "disable_comment": False, "disable_stitch": False, "is_aigc": True,
                               "brand_content_toggle": False, "brand_organic_toggle": False}, "source_info": fonte}
        url = f"{TT}/post/publish/video/init/"
    else:  # rascunho: cai na caixa de entrada do app TikTok do perfil, com a legenda pronta para colar
        corpo, url = {"source_info": fonte}, f"{TT}/post/publish/inbox/video/init/"
    r = requests.post(url, headers=h, json=corpo).json()
    if r.get("error", {}).get("code") != "ok": raise RuntimeError(f"TikTok recusou: {r.get('error')}")
    u = requests.put(r["data"]["upload_url"], data=dados, headers={"Content-Type": "video/mp4", "Content-Length": str(tam),
                                                                    "Content-Range": f"bytes 0-{tam - 1}/{tam}"})
    if u.status_code >= 400: raise RuntimeError(f"upload do TikTok: {u.status_code}")
    return r["data"]["publish_id"]


def main():
    agenda = json.load(open(AGENDA, encoding="utf-8")) if os.path.exists(AGENDA) else []
    meta, ttapp, tttok = env_json("META_UNIDADES"), env_json("TIKTOK_APP"), env_json("TIKTOK_TOKENS")
    if not meta.get("U01_BR_PSICO") and os.environ.get("META_IG"):  # compatibilidade com o segredo antigo
        m = env_json("META_IG"); meta["U01_BR_PSICO"] = {**m, "page_id": m.get("page_id"), "page_token": m.get("page_token")}
    modo = (os.environ.get("TIKTOK_MODO") or "rascunho").strip().lower()
    agora = dt.datetime.now(dt.timezone.utc); mudou = False
    for it in sorted(agenda, key=lambda x: x["quando"]):
        if it.get("status") != "pendente": continue
        quando = dt.datetime.fromisoformat(it["quando"])
        if (quando - agora).total_seconds() > ANTECEDENCIA: continue
        if (agora - quando).total_seconds() > ATRASO_MAX:
            it["status"] = "atrasado"; mudou = True; print(f"atrasado: {it['id']}"); continue
        u, rede = it["unidade"], it["rede"]
        tem = {"instagram": bool(meta.get(u, {}).get("ig_user_id")), "facebook": bool(meta.get(u, {}).get("page_token")),
               "tiktok": bool(ttapp and tttok.get(u))}.get(rede, False)
        if not tem:  # acesso ainda não foi para a nuvem: espera (não conta como falha)
            print(f"⏸ {it['id']}: sem acesso de {rede} para {u} na nuvem (rode segredos_nuvem.bat)"); continue
        try:
            if rede == "instagram":
                if not meta.get(u, {}).get("ig_user_id"): raise RuntimeError(f"sem acesso do Instagram para {u}")
                it["media_id"] = instagram(meta[u], it)
            elif rede == "facebook":
                if not meta.get(u, {}).get("page_token"): raise RuntimeError(f"sem acesso da Página para {u}")
                it["media_id"] = facebook(meta[u], it)
            elif rede == "tiktok":
                if not (ttapp and tttok.get(u)): raise RuntimeError(f"sem acesso do TikTok para {u}")
                it["media_id"] = tiktok(ttapp, tttok[u], it, modo); it["modo"] = modo
            else:
                continue
            it["status"] = "publicado" if not (rede == "tiktok" and modo != "publico") else "rascunho"
            it["em"] = agora.isoformat(); it.pop("erro", None)
            print(f"✅ {it['id']} → {it['status']}")
        except Exception as e:
            it["erro"] = str(e)[:300]; it["tentativas"] = it.get("tentativas", 0) + 1
            if it["tentativas"] >= 3: it["status"] = "erro"
            print(f"❌ {it['id']}: {it['erro']}", file=sys.stderr)
        mudou = True
    if mudou: json.dump(agenda, open(AGENDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("nada vencido" if not mudou else "agenda_v2 atualizada")


if __name__ == "__main__":
    main()
