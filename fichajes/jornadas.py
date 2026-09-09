"""Agrupa los fichajes sueltos en una fila por empleado y dia."""

import collections
import datetime

AVISO_FALTA_SALIDA = "REVISAR: falta la salida"
# Los fichajes intermedios van dentro del propio aviso: son lo que hace falta
# para cuadrar la jornada a mano, y ya no hay una columna donde ponerlos.
AVISO_PARTIDA = "REVISAR: jornada partida — {}"


def _horas_entre(entrada, salida):
    fmt = "%H:%M:%S"
    delta = datetime.datetime.strptime(salida, fmt) - datetime.datetime.strptime(entrada, fmt)
    return round(delta.total_seconds() / 3600, 2)


def agrupar(registros):
    """Una fila por empleado y dia, ordenadas por fecha y nombre.

    Solo se calculan horas cuando hay exactamente dos fichajes:

      - Con uno solo falta la salida. Son el 6% de los dias.
      - Con mas de dos hay jornada partida de verdad, no un marcaje repetido:
        comprobado en agosto, p. ej. 09:47-16:05 y 17:45-18:30. Tomar el
        primero y el ultimo contaria la pausa como trabajada.

    En ambos casos la fila se marca y las horas quedan en blanco, porque en un
    documento que roza la nomina inventar una hora es peor que dejar el hueco.
    """
    dias = collections.defaultdict(list)
    for r in registros:
        e = r["employee"]
        clave = (
            e.get("workno") or "",
            "{} {}".format(e.get("first_name") or "", e.get("last_name") or "").strip(),
            e.get("department") or "",
            r["checktime"][:10],
        )
        dias[clave].append(r["checktime"][11:19])

    filas = []
    for (workno, empleado, departamento, fecha), horas in sorted(dias.items(), key=lambda k: (k[0][3], k[0][1])):
        horas.sort()
        entrada, salida, trabajado, aviso = horas[0], None, None, ""

        if len(horas) == 1:
            aviso = AVISO_FALTA_SALIDA
        elif len(horas) == 2:
            salida = horas[1]
            trabajado = _horas_entre(entrada, salida)
        else:
            salida = horas[-1]
            aviso = AVISO_PARTIDA.format(" ".join(h[:5] for h in horas))

        filas.append({
            "fecha": fecha,
            "workno": workno,
            "empleado": empleado,
            "departamento": departamento,
            "entrada": entrada,
            "salida": salida,
            "horas": trabajado,
            "fichajes": len(horas),
            "todos": " ".join(horas),
            "aviso": aviso,
        })

    return filas


def resumen(filas):
    """Horas y dias por departamento, contando solo las filas completas."""
    total = collections.defaultdict(lambda: {"horas": 0.0, "dias": 0})
    for f in filas:
        if f["horas"] is None:
            continue
        t = total[f["departamento"]]
        t["horas"] += f["horas"]
        t["dias"] += 1
    return {k: {"horas": round(v["horas"], 2), "dias": v["dias"]} for k, v in sorted(total.items())}
