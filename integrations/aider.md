# Using AgentVision with Aider

Aider can't see rendered output either. Two simple integrations:

## 1. Run it inside an Aider session

Use Aider's `/run` to feed a verdict back into the chat:

```
/run agentvision check path/to/index.html --json
```

Aider will offer to add the output to the chat — paste it in, then ask Aider to fix the
reported issues. Repeat until the verdict is `pass`.

## 2. Make it part of your test command

Point Aider's lint/test hook at AgentVision so it runs automatically:

```bash
aider --test-cmd "agentvision check path/to/index.html"
```

`agentvision check` exits non-zero on a FAIL verdict, so Aider treats visual defects like
failing tests and iterates on them.

For semantic critique (not just structural checks), set an API key and use
`agentvision analyze … ` with `--backend anthropic|openai|gemini`.
