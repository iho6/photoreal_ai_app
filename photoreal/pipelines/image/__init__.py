"""Image-domain pipelines."""

from photoreal.pipelines.image.character_depth import CharacterDepthPipeline
from photoreal.pipelines.image.character_inpaint import CharacterInpaintPipeline
from photoreal.pipelines.image.photoreal_gen import PhotorealGenPipeline

__all__ = [
    "PhotorealGenPipeline",
    "CharacterDepthPipeline",
    "CharacterInpaintPipeline",
]
