# Vendored sources

`ming_tiny/` comes from inclusionAI/Ming-3.0-tts commit
`028c1eace193e7acdb256453da89b6e9207e052b`, distributed under its MIT license
in `MING-LICENSE`. Mathematical model components and the released task/prompt
protocol are reused directly; T8 supplies independent loading, Windows kernels,
model lifecycle, UI, Comfy nodes, and product features. Local compatibility or
callback changes are recorded in roadmap.md and Git history when committed.

The portable KDA recurrence follows the MIT-licensed FLA reference by Songlin
Yang, Yu Zhang, Zhiyuan Li and contributors. ConvRot format interoperability
follows the regular Hadamard layout described by Apache-2.0 comfy-kitchen.
Neither ComfyUI's Ming runtime nor an external inference service is imported.

`confucius/` reuses native/audio/VAD/streaming/segmentation/hotword/subtitle
modules from T8mars/comfyui-confucius-r2t2-t8 commit
`9bebc7bb09b2426c43af36b72ac7377f144ac852` under Apache-2.0 in
`CONFUCIUS-LICENSE`. The segmentation subtitle import is made package-relative.
The original HTTP worker and bridge are not included. Model and native binary
assets retain their own provenance and license requirements.

The Confucius adapter uses a private `ming_confucius_native` module name to
avoid colliding with the existing T8 plugin in a host process. It adds explicit
close and atomic cancellation, ABI selection, and matching Torch CUDA DLL lookup.
Repeated content verification caches only unchanged file path/size/mtime tuples.
