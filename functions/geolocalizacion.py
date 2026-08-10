import math


def distancia_km(lat1, lon1, lat2, lon2):
    """Distancia en línea recta entre dos coordenadas (fórmula de Haversine), en km."""

    R = 6371.0

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distancia_entre_perfiles(perfil1, perfil2):
    """None si a alguno de los dos perfiles le falta la ubicación (compartirla
    es opcional en el onboarding, no todos los usuarios la van a tener)."""

    u1 = perfil1.get("ubicacion") or {}
    u2 = perfil2.get("ubicacion") or {}

    if u1.get("lat") is None or u1.get("lng") is None or u2.get("lat") is None or u2.get("lng") is None:
        return None

    return distancia_km(u1["lat"], u1["lng"], u2["lat"], u2["lng"])


def ordenar_por_cercania(perfil_propio, candidatos):
    """candidatos: lista de (uid, perfil). Devuelve la misma lista de tuplas
    (uid, perfil, distancia_km) ordenada de más cerca a más lejos. Los
    candidatos sin ubicación cargada (distancia None) quedan al final -- no se
    descartan, solo no se pueden priorizar por cercanía."""

    con_distancia = [
        (uid, perfil, distancia_entre_perfiles(perfil_propio, perfil))
        for uid, perfil in candidatos
    ]

    con_distancia.sort(key=lambda t: (t[2] is None, t[2]))

    return con_distancia
