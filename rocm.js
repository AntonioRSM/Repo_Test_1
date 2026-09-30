// Accelerazione GPU AMD su Windows (Ryzen AI Max / Radeon RX 7000-9000) per la pipeline audiolibri.
// Le build PyTorch ROCm di AMD per Windows richiedono Python 3.12: si crea un ambiente separato
// (app/env-rocm) che audiobook_job.py usa in automatico quando la GPU è stata verificata (.pronto).
module.exports = {
  run: [
    {
      when: "{{platform !== 'win32'}}",
      method: "notify",
      params: { html: "Questa voce serve solo su Windows. Su Linux con GPU AMD l'installazione standard usa già ROCm." }
    },
    {
      when: "{{platform === 'win32'}}",
      method: "shell.run",
      params: {
        path: "app",
        message: [
          "uv venv --python 3.12 --allow-existing env-rocm",
          "uv pip install --python env-rocm\\Scripts\\python.exe --find-links https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/ --index-strategy unsafe-best-match torch==2.9.1+rocm7.2.1 torchaudio==2.9.1+rocm7.2.1",
          "uv pip install --python env-rocm\\Scripts\\python.exe --find-links https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/ --index-strategy unsafe-best-match f5-tts openai gradio_client pydub soundfile torch==2.9.1+rocm7.2.1 torchaudio==2.9.1+rocm7.2.1",
          "uv pip uninstall --python env-rocm\\Scripts\\python.exe torchcodec",
          "env-rocm\\Scripts\\python.exe gpu_check.py"
        ]
      }
    },
    {
      when: "{{platform === 'win32'}}",
      method: "notify",
      params: { html: "Controlla l'ultima riga del terminale: 'GPU pronta' = la pipeline audiolibri userà la GPU AMD." }
    }
  ]
}
