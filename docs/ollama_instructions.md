Ollama Instructions:

1. Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh`

2. Check version: `ollama --version`

3. Check if Ollama service is running: `systemctl status ollama --no-pager`

4. Enable Ollama if its not running: `sudo systemctl enable --now ollama`

5. Check if Ollama is reachable: `curl -s http://localhost:11434/api/tags | head`

6. Check that verify_ollama.py executes safely: `python scripts/verify_ollama.py --host http://localhost:11434`

7. Pull a model from Ollama: `ollama pull phi3:mini`
`ollama pull qwen2.5:3b`
`ollama pull llama3.2:3b`

8. List existing stored models: `ollama list`

```
(llm) vishal@vishal-ROG:~/codebase/projects/ai_evals_v1$ ollama list
NAME         ID              SIZE      MODIFIED     
phi3:mini    4f2222927938    2.2 GB    14 hours ago 
```


9. Update the `configs/dev+_rog.yaml` file to switch models:

```

ollama:
  host: http://localhost:11434
  model: phi3:mini
  options:
    temperature: 0.2
    num_predict: 256
    num_ctx: 2048

```

10. Check the model prompting works: `ollama run phi3:mini`

11. Sample test: Press `CTRL + D` to exit.

```
CONTEXT:
Company: Apple. Fiscal year: 2023. Net sales (revenue): 394.3 billion USD.

INSTRUCTION:
Using only the context, what is Apple's fiscal 2023 net sales (revenue)? Reply with only the value and unit.
```


12: Run the AI Eval:

`python scripts/run_model_ollama.py --config configs/dev_rog.yaml`



