"""
Pluggable text-to-image backends for lm:image-agent.

The component never touches a model library directly: it asks `get_backend()` for a
backend by name and calls `generate()`, which returns a list of PIL images. Swapping
the underlying model is a matter of changing the `backend` / `model` properties.

Built-in backends (heavy libraries are imported lazily, on first use):
  janus     — DeepSeek Janus-Pro via transformers (default model: Janus-Pro-1B)
  diffusers — any Hugging Face diffusers text-to-image pipeline (default: sd-turbo)

Adding a backend — subclass ImageBackend, implement load() and generate_images(), then
either register it under a short name:

    from noid_collections.lm_agents.image.backends import ImageBackend, register_backend

    class MyBackend(ImageBackend):
        default_model = "org/my-model"
        def load(self): ...
        def generate_images(self, prompt, num_images, seed, guidance_scale, options): ...

    register_backend("mine", MyBackend)

or reference it directly from the scene, without registering, as
"backend": "my_package.my_module:MyBackend".
"""
import importlib
import logging
import threading

logger = logging.getLogger(__name__)


class ImageBackend:
    """Base class: one loaded model, generating images from text prompts.

    Instances are cached and shared by every component that asks for the same
    (backend, model, device, dtype), so the model is loaded once per process.
    Calls to generate() are serialized: a single model instance is not safe to
    run concurrently, and parallel runs would multiply memory use anyway.
    """

    default_model: str = ""
    min_gpu_gb: float = 0.0   # "auto" device picks CUDA only with at least this much memory

    def __init__(self, model: str = "", device: str = "auto", dtype: str = "auto"):
        self.model_id = model or self.default_model
        self.device = device
        self.dtype = dtype
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        """Load the model (blocking; runs off the event loop)."""

    def generate(self, prompt: str, *, num_images: int = 1, seed=None,
                 guidance_scale=None, options: dict = None) -> list:
        """Return a list of PIL images for prompt. Blocking; thread-safe."""
        with self._lock:
            return self.generate_images(prompt, num_images, seed, guidance_scale, options or {})

    def generate_images(self, prompt: str, num_images: int, seed, guidance_scale,
                        options: dict) -> list:
        raise NotImplementedError


# ----------------------------------------------------------------------
# torch helpers (shared by the built-in backends)

def _resolve_device(device: str, min_gpu_gb: float) -> str:
    import torch
    if device and device != "auto":
        return device
    if torch.cuda.is_available():
        total = torch.cuda.get_device_properties(0).total_memory / 2**30
        if total >= min_gpu_gb:
            return "cuda"
    return "cpu"


def _resolve_dtype(dtype: str, default: str):
    import torch
    name = default if not dtype or dtype == "auto" else dtype
    return getattr(torch, name)


# ----------------------------------------------------------------------
# Built-in backends

class JanusBackend(ImageBackend):
    """DeepSeek Janus-Pro (unified multimodal model) through transformers.

    Produces 384x384 images. Options: temperature (float, default 1.0).
    Needs ~4 GB in bfloat16, so "auto" only uses a GPU with >= 6 GB.
    """

    default_model = "deepseek-community/Janus-Pro-1B"   # transformers-native conversion
    min_gpu_gb = 6.0

    def load(self) -> None:
        import torch
        import transformers
        from transformers import JanusForConditionalGeneration, JanusProcessor

        if int(transformers.__version__.split(".")[0]) >= 5:
            logger.warning(
                "transformers %s detected: Janus image generation is known to break in 5.x "
                "(_prepare_static_cache signature mismatch); use transformers<5 if it fails.",
                transformers.__version__,
            )
        self.device = _resolve_device(self.device, self.min_gpu_gb)
        self._dtype = _resolve_dtype(self.dtype, "bfloat16")
        logger.info("Loading %s on %s (%s)", self.model_id, self.device, self._dtype)
        self._torch = torch
        self._processor = JanusProcessor.from_pretrained(self.model_id)
        self._model = JanusForConditionalGeneration.from_pretrained(
            self.model_id, dtype=self._dtype
        ).to(self.device).eval()

    def generate_images(self, prompt, num_images, seed, guidance_scale, options):
        if seed is not None:
            self._torch.manual_seed(int(seed))

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        chat = self._processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self._processor(
            text=chat, generation_mode="image", return_tensors="pt"
        ).to(self.device, dtype=self._dtype)

        tokens = self._model.generate(
            **inputs,
            generation_mode="image",
            do_sample=True,
            temperature=float(options.get("temperature", 1.0)),
            guidance_scale=float(5.0 if guidance_scale is None else guidance_scale),
            num_return_sequences=num_images,
        )
        decoded = self._model.decode_image_tokens(tokens)
        images = self._processor.postprocess(list(decoded.float()), return_tensors="PIL.Image.Image")
        return images["pixel_values"]


class DiffusersBackend(ImageBackend):
    """Any diffusers text-to-image pipeline (Stable Diffusion, SDXL, FLUX, ...).

    Options are passed straight to the pipeline call, e.g. num_inference_steps,
    width, height, negative_prompt. The default sd-turbo is meant to run with
    guidance_scale 0 and options {"num_inference_steps": 1}.
    """

    default_model = "stabilityai/sd-turbo"
    min_gpu_gb = 4.0

    def load(self) -> None:
        import torch
        from diffusers import AutoPipelineForText2Image

        self.device = _resolve_device(self.device, self.min_gpu_gb)
        # half precision is only reliably fast on GPU
        self._dtype = _resolve_dtype(self.dtype, "float16" if self.device == "cuda" else "float32")
        logger.info("Loading %s on %s (%s)", self.model_id, self.device, self._dtype)
        self._torch = torch
        self._pipe = AutoPipelineForText2Image.from_pretrained(
            self.model_id, torch_dtype=self._dtype
        ).to(self.device)

    def generate_images(self, prompt, num_images, seed, guidance_scale, options):
        kwargs = dict(options)
        if guidance_scale is not None:
            kwargs["guidance_scale"] = float(guidance_scale)
        if seed is not None:
            kwargs["generator"] = self._torch.Generator(self.device).manual_seed(int(seed))
        return self._pipe(prompt, num_images_per_prompt=num_images, **kwargs).images


# ----------------------------------------------------------------------
# Registry and cache

_registry: dict = {
    "janus": JanusBackend,
    "diffusers": DiffusersBackend,
}
_cache: dict = {}
_cache_lock = threading.Lock()


def register_backend(name: str, backend_class: type) -> None:
    """Make backend_class available under name (the `backend` property value)."""
    _registry[name] = backend_class


def resolve_backend_class(name: str) -> type:
    """Registered name, or an import path "package.module:ClassName"."""
    if name in _registry:
        return _registry[name]
    if ":" in name:
        module_name, _, attr = name.partition(":")
        return getattr(importlib.import_module(module_name), attr)
    raise ValueError(
        f"Unknown image backend {name!r}; registered: {sorted(_registry)} "
        "(or use 'package.module:ClassName')"
    )


def get_backend(name: str, model: str = "", device: str = "auto", dtype: str = "auto") -> ImageBackend:
    """Return the cached backend instance, loading the model on first use (blocking)."""
    key = (name, model or "", device or "auto", dtype or "auto")
    with _cache_lock:
        if key not in _cache:
            _cache[key] = resolve_backend_class(name)(model=model, device=device, dtype=dtype)
        return _cache[key]
