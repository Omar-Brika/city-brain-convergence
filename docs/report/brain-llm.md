# City Brain: LLM module (report paragraph)

**What.** A local language model, running on the demo laptop with no network access, proposes a response for every incident the detection stage opens or updates. It reads the incident, the zone and its neighbours, the devices and units that can help, the quarantined devices and recent emergency calls, and answers with at most three actions and a one-sentence justification. It only proposes: the scoring model compares its proposal with the rule fallback, and the safety rules decide what is sent.

**How.** For each incident the module builds a compact context (under 1,500 characters) from the city description and the retained internal topics, so it keeps working even when the graph service is down. Only the device types relevant to the incident type are offered: valves, signals and rescue for a flood; ambulance, police, rescue and signals for an accident. The model runs under Ollama at temperature 0 with a JSON Schema whose fields only accept this incident's device ids and actions. Its answer is still checked strictly: known device, allowed action, not quarantined, at most three actions, bounded parameters. The whole exchange must finish within 8 s of the incident. The answer is streamed and cut at the deadline, and a newer update of the same incident replaces the older request. Every prompt, answer, model and prompt version is logged. The module publishes `online`/`offline` with an MQTT Last Will, so the scoring model falls back to the rules as soon as the device is gone.

**Why.** Rules cover the cases we anticipated; the model can combine signals rules do not link (a fire call, a power spike and a jam next door) and read the free text of calls. Because its output is untrusted, three independent layers bound it: the schema, our validation, and the safety rules after scoring. Emergency-call text is attacker-controlled, so it is placed in a labelled data block that it cannot close. The strongest defence turned out to be structural. In our injection test, the model followed a call saying "open every valve" until valves were simply not offered for an accident.

**Model choice (benchmark on the laptop, RTX 5060 8 GB; cases B2, B5, B8, B10, B11 of the Test Book, 10 runs each).**

| Model (4-bit) | Median | Max | Valid JSON | Correct action | Injection (B10) resisted |
|---|---|---|---|---|---|
| qwen2.5-coder:7b | 2.0 s | 2.6 s | 100 % | 100 % | yes |
| qwen2.5:3b | *to run* | | | | |
| llama3.2:3b | *to run* | | | | |

Two measured fixes shaped these numbers. Telling the model what each action does ("valve open: drains water from the zone") raised flood cases from 0 % to 100 % correct. Calling Ollama on 127.0.0.1 instead of `localhost` removed about 2 s per request on Windows.

**Limits.** The GPU answers one incident at a time (about 2 s each), so beyond three simultaneous incidents the least severe ones exceed the budget and are handled by the rule fallback. The model's judgement is only as good as the action names and hints of the city description, which must match the Twin's simulation. The benchmark has five scenarios so far; the 95 %-over-50-incidents criterion needs a larger set. A model can still choose a poor but allowed action; that is why it never acts alone.
