# Mocks

Stand-ins for: twin + guardian

## Mock LLM

`python -m mocks.mock_llm [scripted|slow|offline|invalid]`: the real LLM service (`src/llm/`) with a
scripted backend, so other modules can be tested without the edge device or a GPU. Same topics and
timeline events as the real module; settings in `config/llm.yaml` (`mock`). Details: `brain/README.md`,
LLM module.
