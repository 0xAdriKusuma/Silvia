import os
import site


def setup_cuda_dll_dirs():
    """Windows: daftarkan folder DLL CUDA dari paket pip (nvidia-cublas-cu12, nvidia-cudnn-cu12, torch)
    agar faster-whisper/ctranslate2 bisa menemukan cublas64_12.dll dan cudnn."""
    if os.name != "nt":
        return

    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    for root in roots:
        for sub in (("nvidia", "cublas", "bin"), ("nvidia", "cudnn", "bin"),
                    ("nvidia", "cuda_runtime", "bin"), ("torch", "lib")):
            p = os.path.join(root, *sub)
            if os.path.isdir(p):
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
