# Packages

This directory is the start of the repository's package-oriented layout.

For now it provides stable import facades over the existing implementation:

- `packages.rag_core` -> `core/`
- `packages.kb_pipeline` -> `kb_builder/`
- `packages.shared` -> `utils/`

The implementation has not been fully moved yet, which keeps the system running
without a large import-breaking refactor in one step.

