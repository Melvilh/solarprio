# Computing tasks (a "go" signal)

Some loads must **never lose their power**: a computer, a server, a NAS. Cutting their supply can corrupt data or stop
a backup half way. That is why such machines do not belong in the *on/off* category (which switches a relay or a socket).
solarprio has a separate category for them: **Computing task**.

A task **switches nothing**. solarprio only turns a "go" signal on or off; your own script on the machine decides what to
run when the signal says go. Even a wrong setting cannot cut a power supply through it:

- in Home Assistant the form accepts **only a helper (`input_boolean`)**: it refuses a switch, a socket or a light;
- in the Docker runtime the task publishes `ON` / `OFF` on an MQTT topic (or calls an HTTP address) that you choose.

## When is the signal on?

- **Solar surplus**: when the surplus reaches the task's estimated power plus the start margin, and until it falls under
  that power minus the tolerance. A minimum run time (`min_on_s`) keeps it from flapping.
- **Off-peak periods** (optional): during the off-peak windows, or while a tariff entity says off-peak (for example the
  Linky's tariff period, see [OFFPEAK.md](OFFPEAK.md)). The signal stays on for the whole period. Unlike a heater, a task
  needs **no measured power** and is never "finished": solarprio cannot know when your job ends.
- The task's estimated power counts like any load: it is taken out of the surplus left to lower priorities. It does not
  use the off-peak power budget and does not wait for a heater's turn.

## Set it up (Home Assistant)

1. *Settings > Devices & services > Helpers > Create helper > Toggle*, for example `input_boolean.go_heavy_tasks`.
2. In the solarprio panel: **Add a device**, type **Computing task**. Pick the helper, give an **estimate of the power**
   of the tasks it allows (their extra consumption), a priority, and a **minimum run time** at least as long as a typical
   task. Optionally an off-peak window or tariff entity.
3. On the machine, run something that reads the helper. [`examples/task-go-poll.sh`](../examples/task-go-poll.sh) does it
   with `curl`, from cron:

   ```cron
   */5 * * * *  HA_URL=http://homeassistant.local:8123 GO_ENTITY=input_boolean.go_heavy_tasks \
                COMMAND=/usr/local/bin/my-heavy-job FALLBACK_AFTER=06:30 /usr/local/bin/task-go-poll.sh
   ```

   `HA_TOKEN` (a long-lived access token created in your Home Assistant profile) goes in a file that only root can read,
   never in a repository. The script runs the command **once a day**, counts it as done only if it succeeds, and the
   optional `FALLBACK_AFTER` runs it anyway if no go came, so the daily task is never skipped. If Home Assistant cannot be
   reached, nothing runs before the fallback time.

## Docker runtime

```toml
[[device]]
id = "heavy_tasks"
name = "Heavy computing tasks"
priority = 3
kind = "task"
power_w = 300
min_on_s = 300
  [device.actuator]
  type = "mqtt"
  topic = "home/tasks/heavy/go"
  payload_on = "ON"
  payload_off = "OFF"
```

## What to keep in mind

- **Do not move fixed jobs that depend on each other** (backup chains, watchdogs that expect a time). Only give a "go" to
  jobs that can start late and be stopped or restarted safely.
- The signal does not stop a job that is running when it goes off: the example script never interrupts a command. If you
  need that, build it into your own script, and make the job resumable.
- Never use an *on/off* device, a socket or a relay to power a computer, server or NAS on and off from solarprio.

## What is not verified

Tested with a simulated Home Assistant, a local HTTP server for the script, and a Python MQTT broker. The example script was
run in a shell here but **not on a real machine, cron or Home Assistant token**: try it with a harmless command first.

## En français

La catégorie **Tâche informatique** n'allume ni n'éteint rien : elle envoie seulement un signal « go » sur un **assistant
booléen** (`input_boolean`), que vos scripts lisent. Le formulaire refuse tout interrupteur ou prise, donc on ne peut pas
couper l'alimentation d'un ordinateur, d'un serveur ou d'un NAS par erreur. Le signal passe à « on » avec le surplus solaire
ou pendant les heures creuses (plages horaires ou entité tarifaire du Linky). Aucune mesure de puissance n'est nécessaire, et
une tâche n'est jamais « finie » : c'est votre script qui sait quand le travail se termine. N'utilisez jamais une charge
tout-ou-rien pour un serveur.
