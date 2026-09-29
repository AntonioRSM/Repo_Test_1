"""Interfaccia web: chatta con l'LLM di LM Studio e ascolta le risposte con F5-TTS."""
import os
import sys

import gradio as gr

from tts_bridge import Speaker, ask_lmstudio, list_models, load_config, save_default_voice

cfg = load_config()
speaker = Speaker(cfg)


def lmstudio_status():
    try:
        models = list_models(cfg)
        return f"✅ LM Studio connesso ({cfg['lmstudio_url']}) — modelli: {', '.join(models) or 'nessuno caricato'}"
    except Exception as e:
        return f"❌ LM Studio non raggiungibile su {cfg['lmstudio_url']} ({e}). Avvia il server in LM Studio > Developer."


def _text(content):
    # Gradio 6 può restituire il contenuto come lista di parti {"type": "text", "text": ...}
    if isinstance(content, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content


def chat(message, history, ref_audio, ref_text, speed):
    msgs = [{"role": m["role"], "content": _text(m["content"])} for m in history]
    answer = ask_lmstudio(cfg, message, msgs)
    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": answer}]
    wav = speaker.speak(answer, ref_audio or None, ref_text, speed)
    return history, wav, ""


def save_voice(ref_audio, ref_text):
    if not ref_audio:
        return "⚠️ Carica prima un file audio."
    return f"✅ Voce predefinita salvata in {save_default_voice(cfg, ref_audio, ref_text)}"


def say(text, ref_audio, ref_text, speed):
    return speaker.speak(text, ref_audio or None, ref_text, speed)


t, h = cfg["tts"], cfg["hardware"]
with gr.Blocks(title="F5-TTS + LM Studio") as demo:
    gr.Markdown(f"## F5-TTS + LM Studio\nModello: **{t['name']}** su **{t['device']}** "
                f"(nfe_step {t['nfe_step']}) — GPU: {h['gpu']} {h['vram_gb']} GB, RAM {h['ram_gb']} GB")
    status = gr.Markdown(lmstudio_status())
    gr.Button("Ricontrolla LM Studio", size="sm").click(lmstudio_status, outputs=status)
    with gr.Accordion("Voce di riferimento (clonazione)", open=False):
        gr.Markdown("Carica 5-12 secondi di parlato pulito e scrivine la trascrizione esatta "
                    "(se vuota viene trascritta in automatico). Senza file si usa la voce di esempio.")
        ref_audio = gr.Audio(type="filepath", label="Audio di riferimento",
                             value=cfg.get("ref_audio") or None)
        ref_text = gr.Textbox(label="Trascrizione del riferimento", value=cfg.get("ref_text", ""))
        save_status = gr.Markdown()
        gr.Button("Salva come voce predefinita", size="sm").click(save_voice, [ref_audio, ref_text], save_status)
        speed = gr.Slider(0.5, 1.5, value=1.0, step=0.05, label="Velocità")
    with gr.Tab("Chat con LM Studio"):
        bot = gr.Chatbot(height=350)
        msg = gr.Textbox(label="Messaggio", placeholder="Scrivi e premi Invio")
        audio = gr.Audio(label="Risposta parlata", autoplay=True)
        msg.submit(chat, [msg, bot, ref_audio, ref_text, speed], [bot, audio, msg])
    with gr.Tab("Testo → audio"):
        txt = gr.Textbox(label="Testo", lines=6)
        out = gr.Audio(label="Audio generato")
        gr.Button("Genera", variant="primary").click(say, [txt, ref_audio, ref_text, speed], out)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 7861))
    demo.queue().launch(server_name="127.0.0.1", server_port=port)
