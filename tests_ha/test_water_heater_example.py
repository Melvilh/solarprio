"""The water-heater example of docs/WATER_HEATER_EXAMPLE.md, run against a real Home Assistant: a Linky that reports
withdrawn and injected power as two separate sensors, a template sensor that nets them, and an ESPHome router
simulated by its contract (a setpoint that falls back to 0 W when no order arrives within the timeout)."""
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.solarprio.const import RESEND_EVERY_S

from .test_integration import coordinator, dev, setup

WITHDRAWN = "sensor.garage_esp_teleinfo_linky_puissance"
INJECTED = "sensor.garage_esp_teleinfo_puissance_injectee"
NET = "sensor.reseau_export_net"
SETPOINT = "number.chauffe_eau_consigne_externe_w"
HEATER_POWER = "sensor.chauffe_eau_puissance_chauffe_eau"

TEMPLATE = {"template": [{"sensor": [{
    "name": "Reseau export net",
    "unit_of_measurement": "W",
    "device_class": "power",
    "state": f"{{{{ states('{INJECTED}') | float - states('{WITHDRAWN}') | float }}}}",
    "availability": f"{{{{ has_value('{INJECTED}') and has_value('{WITHDRAWN}') }}}}",
}]}]}

# the device exactly as the documentation tells the user to configure it
HEATER = dev(id="chauffe_eau", name="Chauffe-eau", entity_id=SETPOINT, kind="proportional", priority=1,
             power_w=2400, min_power_w=200, scale="watts", measured_entity=HEATER_POWER, min_on_s=0, min_off_s=0)
DATA = {"mode": "export", "export_entity": NET, "invert": False, "interval_s": 5, "stale_after_s": 60,
        "on_stale": "off", "margin_w": 100}

W = {"unit_of_measurement": "W"}


class SimulatedRouter:
    """What the ESPHome patch promises: the order is only honoured while it is recent."""

    def __init__(self, timeout_s):
        self.timeout_s, self.value, self.last_order = timeout_s, 0.0, None

    def order(self, call, now):
        self.value, self.last_order = float(call.data["value"]), now

    def power(self, now):
        if self.last_order is None or now - self.last_order > self.timeout_s:
            return 0.0
        return min(self.value, 2400.0)


def set_grid(hass, withdrawn, injected):
    hass.states.async_set(WITHDRAWN, str(withdrawn), W)
    hass.states.async_set(INJECTED, str(injected), W)


async def start(hass, clock, router):
    hass.services.async_register("number", "set_value", lambda call: router.order(call, clock[0]))
    set_grid(hass, 0, 800)
    hass.states.async_set(HEATER_POWER, "0", W)
    assert await async_setup_component(hass, "template", TEMPLATE)
    await hass.async_block_till_done()
    return await setup(hass, data=DATA, devices=[HEATER])


async def step(hass, coord, clock, router, seconds=5):
    await hass.async_block_till_done()  # let the template sensor follow the Linky sensors first
    clock[0] += seconds
    hass.states.async_set(HEATER_POWER, str(router.power(clock[0])), W)
    await coord.async_refresh()
    await hass.async_block_till_done()


async def test_template_nets_injected_and_withdrawn_power(hass: HomeAssistant):
    assert await async_setup_component(hass, "template", TEMPLATE)
    set_grid(hass, 0, 800)
    await hass.async_block_till_done()
    assert float(hass.states.get(NET).state) == 800
    set_grid(hass, 300, 0)
    await hass.async_block_till_done()
    assert float(hass.states.get(NET).state) == -300
    hass.states.async_set(INJECTED, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(NET).state == "unavailable"  # never a made-up number


async def test_heater_gets_the_surplus_minus_the_margin_and_stays_stable(hass: HomeAssistant):
    clock, router = [1000.0], SimulatedRouter(timeout_s=120)
    with patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: clock[0])):
        entry = await start(hass, clock, router)
        coord = coordinator(hass, entry)
        assert router.value == 700.0  # 800 W exported - 100 W margin

        # the heater now draws 700 W, so the meter shows 100 W injected: the order must not move
        set_grid(hass, 0, 100)
        for _ in range(3):
            await step(hass, coord, clock, router)
            assert router.value == 700.0
        assert coord.engine.routed_w == 700.0


async def test_losing_the_measurement_orders_zero(hass: HomeAssistant):
    clock, router = [1000.0], SimulatedRouter(timeout_s=120)
    with patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: clock[0])):
        entry = await start(hass, clock, router)
        coord = coordinator(hass, entry)
        assert router.value == 700.0
        hass.states.async_set(INJECTED, "unavailable")  # the garage ESP drops off the network
        await hass.async_block_till_done()
        await step(hass, coord, clock, router)
        assert router.value == 0.0


async def test_heartbeat_keeps_the_router_inside_its_120s_watchdog(hass: HomeAssistant):
    clock, router = [1000.0], SimulatedRouter(timeout_s=120)
    with patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: clock[0])):
        entry = await start(hass, clock, router)
        coord = coordinator(hass, entry)
        set_grid(hass, 0, 100)  # steady state: the order never changes
        for _ in range(int(600 / 5)):  # ten minutes
            await step(hass, coord, clock, router)
            assert router.power(clock[0]) == 700.0, f"watchdog fired at t={clock[0]}"


async def test_negative_control_a_too_short_timeout_would_fall_to_zero(hass: HomeAssistant):
    """Proves the test above can fail: with a timeout shorter than the heartbeat the simulated router drops out."""
    clock, router = [1000.0], SimulatedRouter(timeout_s=RESEND_EVERY_S - 10)
    with patch("custom_components.solarprio.coordinator.time", SimpleNamespace(monotonic=lambda: clock[0])):
        entry = await start(hass, clock, router)
        coord = coordinator(hass, entry)
        set_grid(hass, 0, 100)
        seen_zero = False
        for _ in range(int(120 / 5)):
            await step(hass, coord, clock, router)
            seen_zero = seen_zero or router.power(clock[0]) == 0.0
        assert seen_zero
