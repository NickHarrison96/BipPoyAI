# Config Integration Scratchpad

## Settings to integrate from config.py into GUI

| Setting | Current Value | GUI Element |
|---------|---------------|-------------|
| ENGINE_MODE | direct | Dropdown (direct, litellm_standard, litellm_chat) |
| CONTEXT_SIZE | 4096 | Input field |
| GPU_OFFLOAD_LAYERS | 32 | Input field |
| CPU_THREADS | 4 | Input field |
| BATCH_SIZE | 1 | Input field |
| TEMPERATURE | 0.7 | Input field |
| MODEL_TAG | Qwythos-9B | Input field |
| MODEL_NICKNAME | Qwythos-9B | Input field |
| LITELLM_PROXY_URL | http://localhost:4000 | Input field |
| LITELLM_PROXY_API_KEY | ollama | Input field |
| LITELLM_PROXY_MODEL | qwen2.5-coder:7b | Input field |
| OLLAMA_BASE_URL | http://localhost:11434 | Input field |
| OLLAMA_MODEL | qwen2.5-coder:7b | Input field |

## Progress

- [ ] ENGINE_MODE - Dropdown with values from config.py
- [ ] CONTEXT_SIZE - Input field
- [ ] GPU_OFFLOAD_LAYERS - Input field
- [ ] CPU_THREADS - Input field
- [ ] BATCH_SIZE - Input field
- [ ] TEMPERATURE - Input field
- [ ] MODEL_TAG - Input field
- [ ] MODEL_NICKNAME - Input field
- [ ] LITELLM_PROXY_URL - Input field
- [ ] LITELLM_PROXY_API_KEY - Input field
- [ ] LITELLM_PROXY_MODEL - Input field
- [ ] OLLAMA_BASE_URL - Input field
- [ ] OLLAMA_MODEL - Input field

## Implementation Steps

1. Add import config at top of main.py
2. Modify GUI initialization to load defaults from config.py
3. Add save functionality to write GUI values back to config.py
4. Add a "Save to config" button or menu item

## Notes

- Need to verify that the GUI currently has these fields or add them
- Check if values are being read from config.py or hardcoded
- May need to add a "Load from config" button
