#!/usr/bin/env python3
"""
Monitor de notas USAC - Detecta cuando se publican notas en Parcial 2
y notifica vía Telegram.
"""

import os
import sys
import json
import hashlib
import requests
import pdfplumber
import io
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIGURACIÓN DE CURSOS
#  Agrega más URLs aquí según necesites
# ─────────────────────────────────────────────
CURSOS = [
    {
        "nombre": "	205 INTRODUCCION AL DERECHO I (N)",
        "url": "https://usacderecho.com/adminasigna/cartelera_pdf/2026_1_205_D.pdf",
    },  
    {
        "nombre": "204 COMUNICACION",
        "url": "https://usacderecho.com/adminasigna/cartelera_pdf/2026_1_204_D.pdf",
    },
    {
        "nombre": "203 CIENCIA POLITICA",
        "url": "https://usacderecho.com/adminasigna/cartelera_pdf/2026_1_203_D.pdf",
    },
    {
        "nombre": "202 ECONOMIA",
        "url": "https://usacderecho.com/adminasigna/cartelera_pdf/2026_1_202_D.pdf",
    },  
    {
        "nombre": "TEORIA DE LA INVESTIGACION",
        "url": "https://usacderecho.com/adminasigna/cartelera_pdf/2026_1_201_D.pdf",
    },               

]

# Columna que se monitorea (texto que aparece en el encabezado)
COLUMNA_OBJETIVO = "Parcial 2"

# Archivo donde se guarda el estado previo (en el repo como artefacto)
STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}


# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """Envía un mensaje por Telegram. Retorna True si fue exitoso."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        print(f"✅ Telegram enviado: {message[:60]}...")
        return True
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")
        return False


# ─────────────────────────────────────────────
#  DESCARGA Y PARSEO DEL PDF
# ─────────────────────────────────────────────

def download_pdf(url: str) -> bytes | None:
    """Descarga el PDF y retorna los bytes, o None si falla."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        if "pdf" not in r.headers.get("Content-Type", "").lower() and len(r.content) < 1000:
            print(f"  ⚠️  Respuesta sospechosa (posible bloqueo): {r.status_code} {len(r.content)} bytes")
            return None
        print(f"  📥 PDF descargado: {len(r.content):,} bytes")
        return r.content
    except Exception as e:
        print(f"  ❌ Error descargando PDF: {e}")
        return None


def extract_parcial2_data(pdf_bytes: bytes) -> dict:
    """
    Extrae las notas de la columna 'Parcial 2' del PDF.
    Retorna un dict con:
      - col_index: índice de la columna encontrada (None si no existe)
      - rows: lista de filas relevantes [{carnet, nombre, nota}]
      - has_data: True si la columna tiene al menos un valor no vacío
      - hash: hash del contenido relevante
    """
    result = {
        "col_index": None,
        "rows": [],
        "has_data": False,
        "hash": None,
        "raw_text": "",
    }

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue

                    # Buscar encabezado con "Parcial 2"
                    header = [str(c).strip() if c else "" for c in table[0]]
                    col_idx = None
                    for i, h in enumerate(header):
                        if COLUMNA_OBJETIVO.lower() in h.lower():
                            col_idx = i
                            break

                    if col_idx is None:
                        continue

                    result["col_index"] = col_idx
                    print(f"  📋 Encabezados encontrados: {header}")
                    print(f"  🎯 Columna '{COLUMNA_OBJETIVO}' en índice {col_idx}")

                    rows_data = []
                    for row in table[1:]:
                        if not row or all(c is None or str(c).strip() == "" for c in row):
                            continue
                        nota = str(row[col_idx]).strip() if col_idx < len(row) else ""
                        # Carnet usualmente en col 0, nombre en col 1 o 2
                        carnet = str(row[0]).strip() if row[0] else ""
                        nombre = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                        rows_data.append({
                            "carnet": carnet,
                            "nombre": nombre,
                            "nota": nota,
                        })
                        if nota and nota not in ("", "None", "-", "0"):
                            result["has_data"] = True

                    result["rows"] = rows_data

                    # Hash del contenido de la columna para detectar cambios
                    col_content = "|".join(r["nota"] for r in rows_data)
                    result["hash"] = hashlib.md5(col_content.encode()).hexdigest()
                    result["raw_text"] = col_content
                    return result  # Primera tabla válida encontrada

        # Si no hubo tablas, intentar con texto plano
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            result["raw_text"] = full_text
            result["hash"] = hashlib.md5(full_text.encode()).hexdigest()
            if COLUMNA_OBJETIVO.lower() in full_text.lower():
                result["col_index"] = -1  # encontrado en texto plano
                print("  📄 Columna encontrada en texto plano (sin tabla estructurada)")

    except Exception as e:
        print(f"  ❌ Error parseando PDF: {e}")

    return result


# ─────────────────────────────────────────────
#  ESTADO PERSISTENTE
# ─────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print(f"💾 Estado guardado en {STATE_FILE}")


# ─────────────────────────────────────────────
#  LÓGICA PRINCIPAL
# ─────────────────────────────────────────────

def check_curso(curso: dict, prev_state: dict) -> dict:
    """
    Revisa un curso y retorna el nuevo estado.
    Envía notificación Telegram si hay cambios.
    """
    nombre = curso["nombre"]
    url    = curso["url"]
    key    = hashlib.md5(url.encode()).hexdigest()[:8]  # clave única por URL

    print(f"\n{'='*50}")
    print(f"📚 Revisando: {nombre}")
    print(f"   URL: {url}")

    pdf_bytes = download_pdf(url)
    if pdf_bytes is None:
        print("  ⏭️  Saltando (no se pudo descargar)")
        return prev_state.get(key, {})

    data = extract_parcial2_data(pdf_bytes)
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prev = prev_state.get(key, {})
    prev_hash     = prev.get("hash")
    prev_had_data = prev.get("has_data", False)

    new_state = {
        "nombre": nombre,
        "url": url,
        "hash": data["hash"],
        "has_data": data["has_data"],
        "col_found": data["col_index"] is not None,
        "last_checked": now,
        "last_changed": prev.get("last_changed", now),
    }

    # Detectar cambios
    if data["hash"] != prev_hash:
        new_state["last_changed"] = now
        print(f"  🔄 CAMBIO DETECTADO (hash anterior: {prev_hash} → nuevo: {data['hash']})")

        if data["has_data"] and not prev_had_data:
            # ¡Notas nuevas publicadas!
            msg = build_notification(nombre, url, data, "new_grades")
            send_telegram(msg)

        elif data["has_data"] and prev_had_data:
            # Notas actualizadas
            msg = build_notification(nombre, url, data, "updated_grades")
            send_telegram(msg)

        elif data["col_index"] is None:
            print("  ℹ️  Columna 'Parcial 2' no encontrada en el PDF")
        else:
            print("  ℹ️  Cambio detectado pero sin notas en Parcial 2 aún")
    else:
        print(f"  ✅ Sin cambios (hash: {data['hash']})")
        if not data["has_data"]:
            print(f"  ⏳ Parcial 2 todavía sin notas publicadas")

    return new_state


def build_notification(nombre: str, url: str, data: dict, tipo: str) -> str:
    """Construye el mensaje de Telegram."""
    emoji = "🎉" if tipo == "new_grades" else "📝"
    accion = "¡Ya están disponibles!" if tipo == "new_grades" else "Fueron actualizadas"
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Resumen de notas (primeras 10 filas con nota)
    notas_sample = [r for r in data["rows"] if r["nota"] and r["nota"] not in ("", "None", "-")]
    sample_text = ""
    if notas_sample:
        lines = []
        for r in notas_sample[:10]:
            lines.append(f"  • {r['carnet']} {r['nombre']}: <b>{r['nota']}</b>")
        sample_text = "\n" + "\n".join(lines)
        if len(notas_sample) > 10:
            sample_text += f"\n  <i>...y {len(notas_sample)-10} más</i>"

    return (
        f"{emoji} <b>Notas de {COLUMNA_OBJETIVO} publicadas</b>\n\n"
        f"📚 <b>Curso:</b> {nombre}\n"
        f"📅 <b>Detectado:</b> {now}\n"
        f"✅ <b>Estado:</b> {accion}"
        f"{sample_text}\n\n"
        f"🔗 <a href='{url}'>Ver PDF completo</a>"
    )


def main():
    print(f"🚀 Monitor de Notas USAC — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Columna monitoreada: '{COLUMNA_OBJETIVO}'")
    print(f"   Cursos configurados: {len(CURSOS)}")

    state = load_state()
    new_state = {}

    for curso in CURSOS:
        key = hashlib.md5(curso["url"].encode()).hexdigest()[:8]
        new_state[key] = check_curso(curso, state)

    save_state(new_state)
    print(f"\n✅ Revisión completada — {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
