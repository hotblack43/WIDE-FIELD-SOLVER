"""Sun-only heliocentric two-body propagation and osculating elements."""

from __future__ import annotations

import math

import numpy as np

from .types import HeliocentricState, OrbitalElements


GAUSSIAN_GRAVITATIONAL_CONSTANT_AU32_DAY = 0.01720209895
SOLAR_GM_AU3_DAY2 = GAUSSIAN_GRAVITATIONAL_CONSTANT_AU32_DAY**2


def _stumpff(z: float) -> tuple[float, float]:
    if z > 1e-8:
        root = math.sqrt(z)
        return (1.0 - math.cos(root)) / z, (root - math.sin(root)) / root**3
    if z < -1e-8:
        root = math.sqrt(-z)
        return (math.cosh(root) - 1.0) / (-z), (math.sinh(root) - root) / root**3
    z2 = z * z
    return 0.5 - z / 24.0 + z2 / 720.0, 1.0 / 6.0 - z / 120.0 + z2 / 5040.0


def _validated_state(state: HeliocentricState) -> tuple[np.ndarray, np.ndarray]:
    position = np.asarray(state.position_au, dtype=float)
    velocity = np.asarray(state.velocity_au_per_day, dtype=float)
    if position.shape != (3,) or velocity.shape != (3,) or not np.isfinite(position).all() or not np.isfinite(velocity).all():
        raise ValueError("heliocentric state needs finite position and velocity 3-vectors")
    if np.linalg.norm(position) <= 0.0 or not math.isfinite(state.reference_jd_tdb):
        raise ValueError("heliocentric state needs a positive radius and finite epoch")
    return position, velocity


def _propagate_one(position: np.ndarray, velocity: np.ndarray, delta_days: float) -> tuple[np.ndarray, np.ndarray]:
    if delta_days == 0.0:
        return position.copy(), velocity.copy()
    mu = SOLAR_GM_AU3_DAY2
    sqrt_mu = math.sqrt(mu)
    radius0 = float(np.linalg.norm(position))
    speed2 = float(velocity @ velocity)
    radial_velocity = float(position @ velocity) / radius0
    alpha = 2.0 / radius0 - speed2 / mu
    chi = sqrt_mu * delta_days * alpha if abs(alpha) > 1e-10 else sqrt_mu * delta_days / radius0
    if chi == 0.0:
        chi = math.copysign(1e-12, delta_days)

    for _ in range(100):
        z = alpha * chi * chi
        c, s = _stumpff(z)
        function = (
            radius0 * radial_velocity / sqrt_mu * chi * chi * c
            + (1.0 - alpha * radius0) * chi**3 * s
            + radius0 * chi
            - sqrt_mu * delta_days
        )
        derivative = (
            radius0 * radial_velocity / sqrt_mu * chi * (1.0 - z * s)
            + (1.0 - alpha * radius0) * chi * chi * c
            + radius0
        )
        if not math.isfinite(derivative) or derivative == 0.0:
            raise RuntimeError("universal-variable derivative became singular")
        step = function / derivative
        chi -= step
        if abs(step) < 1e-13:
            break
    else:
        raise RuntimeError("universal-variable propagation did not converge")

    z = alpha * chi * chi
    c, s = _stumpff(z)
    f = 1.0 - chi * chi / radius0 * c
    g = delta_days - chi**3 / sqrt_mu * s
    propagated_position = f * position + g * velocity
    radius = float(np.linalg.norm(propagated_position))
    if radius <= 0.0 or not math.isfinite(radius):
        raise RuntimeError("two-body propagation produced an invalid radius")
    f_dot = sqrt_mu / (radius * radius0) * (alpha * chi**3 * s - chi)
    g_dot = 1.0 - chi * chi / radius * c
    propagated_velocity = f_dot * position + g_dot * velocity
    return propagated_position, propagated_velocity


def propagate_two_body(
    state: HeliocentricState,
    target_jd_tdb: np.ndarray,
) -> np.ndarray:
    position, velocity = _validated_state(state)
    targets = np.atleast_1d(np.asarray(target_jd_tdb, dtype=float))
    if targets.ndim != 1 or not np.isfinite(targets).all():
        raise ValueError("target epochs must be a finite one-dimensional array")
    output = np.empty((len(targets), 2, 3), dtype=float)
    for index, target in enumerate(targets):
        output[index] = _propagate_one(position, velocity, float(target - state.reference_jd_tdb))
    return output


def state_to_elements(state: HeliocentricState) -> OrbitalElements:
    position, velocity = _validated_state(state)
    mu = SOLAR_GM_AU3_DAY2
    radius = float(np.linalg.norm(position))
    speed2 = float(velocity @ velocity)
    angular_momentum = np.cross(position, velocity)
    h_norm = float(np.linalg.norm(angular_momentum))
    if h_norm <= 0.0:
        raise ValueError("radial state has undefined orbital plane")
    node = np.cross([0.0, 0.0, 1.0], angular_momentum)
    node_norm = float(np.linalg.norm(node))
    eccentricity_vector = np.cross(velocity, angular_momentum) / mu - position / radius
    eccentricity = float(np.linalg.norm(eccentricity_vector))
    energy = speed2 / 2.0 - mu / radius
    if energy >= 0.0:
        raise ValueError("v1 orbital elements require a bound heliocentric state")
    semimajor = -mu / (2.0 * energy)
    inclination = math.degrees(math.acos(float(np.clip(angular_momentum[2] / h_norm, -1.0, 1.0))))
    flags: list[str] = []
    tolerance = 1e-10
    if node_norm <= tolerance:
        longitude_node = None
        flags.append("equatorial")
    else:
        longitude_node = math.degrees(math.atan2(node[1], node[0])) % 360.0
    if eccentricity <= tolerance:
        argument_perihelion = None
        mean_anomaly = None
        flags.append("circular")
    else:
        if node_norm <= tolerance:
            argument_perihelion = None
        else:
            cos_argument = float(np.clip(node @ eccentricity_vector / (node_norm * eccentricity), -1.0, 1.0))
            sin_argument = float(
                np.dot(np.cross(node, eccentricity_vector), angular_momentum)
                / (node_norm * eccentricity * h_norm)
            )
            argument_perihelion = math.degrees(math.atan2(sin_argument, cos_argument)) % 360.0
        cos_eccentric = float(np.clip((1.0 - radius / semimajor) / eccentricity, -1.0, 1.0))
        sin_eccentric = float(position @ velocity / (eccentricity * math.sqrt(mu * semimajor)))
        eccentric_anomaly = math.atan2(sin_eccentric, cos_eccentric)
        mean_anomaly = math.degrees(eccentric_anomaly - eccentricity * math.sin(eccentric_anomaly)) % 360.0
    return OrbitalElements(
        reference_jd_tdb=float(state.reference_jd_tdb),
        semimajor_axis_au=float(semimajor),
        eccentricity=eccentricity,
        inclination_deg=inclination,
        longitude_ascending_node_deg=longitude_node,
        argument_perihelion_deg=argument_perihelion,
        mean_anomaly_deg=mean_anomaly,
        singular_flags=tuple(flags),
    )


def elements_to_state(elements: OrbitalElements) -> HeliocentricState:
    required_angles = (
        elements.longitude_ascending_node_deg,
        elements.argument_perihelion_deg,
        elements.mean_anomaly_deg,
    )
    if any(value is None for value in required_angles):
        raise ValueError("Cartesian conversion requires nonsingular angular elements")
    a = float(elements.semimajor_axis_au)
    e = float(elements.eccentricity)
    if not (math.isfinite(a) and a > 0.0 and math.isfinite(e) and 0.0 <= e < 1.0):
        raise ValueError("v1 Cartesian conversion requires a bound elliptical orbit")
    mean_anomaly = math.radians(float(elements.mean_anomaly_deg))
    eccentric_anomaly = mean_anomaly
    for _ in range(50):
        step = (eccentric_anomaly - e * math.sin(eccentric_anomaly) - mean_anomaly) / (
            1.0 - e * math.cos(eccentric_anomaly)
        )
        eccentric_anomaly -= step
        if abs(step) < 1e-14:
            break
    else:
        raise RuntimeError("Kepler equation did not converge")

    cos_e = math.cos(eccentric_anomaly)
    sin_e = math.sin(eccentric_anomaly)
    root = math.sqrt(1.0 - e * e)
    radius = a * (1.0 - e * cos_e)
    perifocal_position = np.array([a * (cos_e - e), a * root * sin_e, 0.0])
    factor = math.sqrt(SOLAR_GM_AU3_DAY2 * a) / radius
    perifocal_velocity = factor * np.array([-sin_e, root * cos_e, 0.0])

    node = math.radians(float(elements.longitude_ascending_node_deg))
    inclination = math.radians(float(elements.inclination_deg))
    perihelion = math.radians(float(elements.argument_perihelion_deg))
    c_o, s_o = math.cos(node), math.sin(node)
    c_i, s_i = math.cos(inclination), math.sin(inclination)
    c_w, s_w = math.cos(perihelion), math.sin(perihelion)
    rotation = np.array(
        [
            [c_o * c_w - s_o * s_w * c_i, -c_o * s_w - s_o * c_w * c_i, s_o * s_i],
            [s_o * c_w + c_o * s_w * c_i, -s_o * s_w + c_o * c_w * c_i, -c_o * s_i],
            [s_w * s_i, c_w * s_i, c_i],
        ]
    )
    position = rotation @ perifocal_position
    velocity = rotation @ perifocal_velocity
    return HeliocentricState(
        reference_jd_tdb=float(elements.reference_jd_tdb),
        position_au=tuple(float(value) for value in position),
        velocity_au_per_day=tuple(float(value) for value in velocity),
    )
