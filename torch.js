// Installa PyTorch adatto alla GPU rilevata da Pinokio (NVIDIA CUDA, AMD ROCm, Apple MPS o CPU)
module.exports = {
  run: [
    // NVIDIA (Windows / Linux) - CUDA 12.8, supporta anche le RTX serie 50
    {
      when: "{{(platform === 'win32' || platform === 'linux') && gpu === 'nvidia'}}",
      method: "shell.run",
      params: {
        venv: "{{args.venv}}",
        path: "{{args.path}}",
        message: "uv pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128 --force-reinstall"
      }
    },
    // AMD su Linux - ROCm
    {
      when: "{{platform === 'linux' && gpu === 'amd'}}",
      method: "shell.run",
      params: {
        venv: "{{args.venv}}",
        path: "{{args.path}}",
        message: "uv pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/rocm6.3 --force-reinstall"
      }
    },
    // macOS (Apple Silicon usa MPS)
    {
      when: "{{platform === 'darwin'}}",
      method: "shell.run",
      params: {
        venv: "{{args.venv}}",
        path: "{{args.path}}",
        message: "uv pip install torch==2.7.0 torchaudio==2.7.0 --force-reinstall"
      }
    },
    // Tutto il resto: CPU
    {
      when: "{{!(platform === 'darwin' || ((platform === 'win32' || platform === 'linux') && gpu === 'nvidia') || (platform === 'linux' && gpu === 'amd'))}}",
      method: "shell.run",
      params: {
        venv: "{{args.venv}}",
        path: "{{args.path}}",
        message: "uv pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cpu --force-reinstall"
      }
    }
  ]
}
