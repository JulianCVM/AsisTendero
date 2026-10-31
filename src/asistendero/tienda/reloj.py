"""Hora de la tienda: zona de Bogotá, días de la semana y el reloj que las pruebas reemplazan.

Colombia no cambia de hora en el año: un desfase fijo evita depender de tzdata en Windows. Quien necesita «ahora» en
hora de la tienda llama ``reloj.local_now()`` por el módulo, para que una prueba o el evaluador fijen el día y la hora
en un solo lugar (``monkeypatch.setattr(reloj, "local_now", ...)``).
"""

from datetime import datetime, timedelta, timezone

BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def local_now() -> datetime:
    """Hora local de la tienda; las pruebas la reemplazan para fijar el día y la hora."""
    return datetime.now(BOGOTA)
