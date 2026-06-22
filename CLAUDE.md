# noid-collections

This project implements noid components — reusable building blocks for the mundorum
ecosystem. All components follow the **noid component model** defined in the sibling
project at `~/git/mundorum/noid`.

## Companion project

**Always load `~/git/mundorum/noid` as an additional working directory.**
It is the framework this project depends on and the authoritative source of truth
for all component APIs.

## Additional directories

- `~/git/mundorum/noid` — noid framework; always load alongside this project.
- `~/git/mundorum/oid` — JS oid library; consult when implementing the Python side of a component that has a JS UI counterpart.

## Before implementing any component

Read these documents **in full** before writing any code:

1. `~/git/mundorum/noid/docs/component-authoring-guide.md` — the complete authoring
   reference. Critical sections: handler naming (§5), the `receive` requirement (§6),
   lifecycle overrides (§10), anti-patterns (§15), testing patterns (§16).
2. `~/git/mundorum/noid/docs/component-model.md` — spec field reference and examples.
3. `~/git/mundorum/noid/docs/architecture.md` — design invariants and decision log.

## Invariants — never violate

- Components import only from `noid.core.component` (`Noid`, `OidComponent`).
- No web framework or workflow engine imports inside component code.
- The Bus is the only communication channel — no direct component-to-component calls.
- `await super().start()` is always the **first** statement in any `start()` override.
- `await super().stop()` is always the **last** statement in any `stop()` override.
- `await self._notify(notice, message)` is always awaited.
- Tests always use `Bus()` (fresh instance), never `Bus.i`.

## Mandatory imports

```python
from noid.core.bus import Bus
from noid.core.component import Noid, OidComponent
```

## Key API at a glance

```python
# Register a component type
@Noid.component({
    "id": "mypkg:name",          # required; "namespace:name" convention
    "properties": {
        "key": {"default": val}, # optional default; optional "readonly": True
    },
    "receive":   ["notice"],     # required for handler dispatch
    "subscribe": "topic~notice", # bus topic → internal notice  (;-separated)
    "publish":   "notice~topic", # internal notice → bus topic  (;-separated)
    "provide":   ["itf:name"],   # interfaces this component exposes
    "connect":   "itf:name#id",  # interfaces this component consumes
})
class MyOid(OidComponent):
    def handle_notice(self, notice, message): ...    # sync handler
    async def handle_other(self, notice, message):  # or async
        await self._notify("out", {"result": ...})
```

```python
# Register an interface (before any component that uses it)
Noid.c_interface({
    "id": "itf:transfer",
    "response": True,            # True → _invoke returns list from all providers
    "operations": {"send": {}},
})
```

```python
# Instantiate
comp = Noid.create("mypkg:name", {"key": val}, bus=bus, component_instance_id="c1")
await comp.start()
# ... active ...
await comp.stop()
```

```python
# Lifecycle override pattern (background task)
async def start(self) -> None:
    await super().start()                          # FIRST
    self._task = asyncio.create_task(self._run())

async def stop(self) -> None:
    task = getattr(self, "_task", None)
    if task and not task.done():
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    await super().stop()                           # LAST
```

## Handler naming

| Notice in spec | Python method |
|---|---|
| `"update"` | `handle_update` |
| `"updateValue"` (camelCase) | `handle_update_value` |
| interface operation `"send"` | `handle_send` |

## Component namespace

All SLM-agents components use the `slm` namespace: `slm:component-name`.

## Package layout

```
noid_collections/
  slm_agents/
    llm/             slm:llm-agent    — Ollama LLM, configurable model
    text_source/     data:text-source  — publish static text on trigger
    csv_source/      data:csv-source   — publish full table or row-by-row
    console_display/ basic:console-display — print to console
    ner/             lm:ner          — Named Entity Recognition (transformers)
    sql/             data:sql          — SQL query via DuckDB or SQLite
    prolog/          logic:prolog       — SWI-Prolog via PySwip
scenes/
  slm_demo.json      — NoidPlayer demo wiring all components
```

## Scene JSON (NoidPlayer)

Scene files live in `scenes/`. Use this format:

```json
{
  "title": "Scene name",
  "imports": ["../noid_collections/slm_agents/llm/llm.py"],
  "components": [
    {
      "type":       "slm:llm-agent",
      "id":         "agent1",
      "properties": {"model": "llama3.2", "prompt_template": "Answer: {input}"},
      "subscribe":  "pipeline/start~input",
      "publish":    "output~pipeline/llm-out"
    }
  ]
}
```

Run: `noid-play scenes/slm_demo.json`

## Testing pattern

```python
import pytest
from noid.core.bus import Bus
from noid.core.component import Noid, OidComponent

async def test_my_component() -> None:
    bus = Bus()          # always fresh; never Bus.i
    received = []
    bus.subscribe("output/topic", lambda t, m: received.append(m))

    comp = MyOid(bus=bus, subscribe="input/topic~notice")
    await comp.start()
    await bus.publish("input/topic", {"value": 1})
    assert received == [{"result": 2}]
    await comp.stop()
```

## Component checklist

Before submitting any component:

- [ ] `id` is `slm:component-name`, unique in this project
- [ ] Every name in `receive` has a matching `handle_*` method
- [ ] `await super().start()` is first in any `start()` override
- [ ] `await super().stop()` is last in any `stop()` override
- [ ] All `_notify` calls are awaited
- [ ] `component_id` is set when using `provide`
- [ ] Interface registered before components that use it
- [ ] At least one test exercises the component via the bus
- [ ] Tests use `Bus()` (not `Bus.i`)
- [ ] No web framework imports in component code
