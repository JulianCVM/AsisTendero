"""Ampliación ficticia del catálogo de la ferretería (31-10-2026): productos que cubren huecos del surtido.

Restricción para no cambiar el sentido de los casos ya medidos: ninguna familia nueva repite la palabra con que
un caso existente nombra un producto (candado, cinta, silicona, bolsa, bombillo, pintura, tornillo, chazo,
varilla, malla), así que ningún caso que hoy cotiza directo pasa a tener que elegir. Las palabras nuevas sí
crean ambigüedades propias (dos cerraduras, dos tablas), que miden los casos de la suite «ampliacion».
"""

# (prefijo, nombre, unidad, categoría, términos, [(código, variante, precio COP)])
EXTRA_FAMILIES = [
    # Maderas
    ("TAB", "Tabla de pino", "unidad", "Maderas", "tabla|madera|pino|bruta", [
        ("1X10", "1 x 10 pulgadas x 3 m", 24900), ("1X12", "1 x 12 pulgadas x 3 m", 29900)]),
    ("MDF", "Tablero MDF", "unidad", "Maderas", "mdf|tablero|lamina|madera|aglomerado", [
        ("9", "9 mm 1,83 x 2,44 m", 74900), ("15", "15 mm 1,83 x 2,44 m", 109900)]),
    ("VMD", "Palo redondo de madera", "unidad", "Maderas", "palo|redondo|madera|vara|escoba", [
        ("12", "1/2 pulgada x 1 m", 2900), ("34", "3/4 pulgada x 1 m", 4400), ("ESC", "para escoba 1,20 m", 3900)]),
    # Adhesivos y sellantes
    ("PEI", "Pegamento instantáneo", "unidad", "Adhesivos y sellantes", "pegamento|instantaneo|gotita|cianoacrilato", [
        ("3G", "3 g", 3500)]),
    ("MSM", "Masilla para madera", "unidad", "Adhesivos y sellantes", "masilla|madera|resanar|huecos", [
        ("CED", "cedro 1/4 de galón", 18900), ("PIN", "pino 1/4 de galón", 18900)]),
    ("SPU", "Sellante de poliuretano", "unidad", "Adhesivos y sellantes", "sellante|poliuretano|juntas|cartucho", [
        ("BLA", "blanco 300 ml", 24900), ("GRI", "gris 300 ml", 24900)]),
    # Jardín y aseo
    ("RAS", "Rastrillo", "unidad", "Jardín y aseo", "rastrillo|jardin|hojas", [
        ("MET", "metálico de 14 dientes", 21900), ("PLA", "plástico para hojas", 14900)]),
    ("MCH", "Machete", "unidad", "Jardín y aseo", "machete|rula|rozar|jardin", [
        ("18", "18 pulgadas", 26900), ("24", "24 pulgadas", 31900)]),
    ("FUM", "Fumigadora manual", "unidad", "Jardín y aseo", "fumigadora|aspersora|bomba|rociar", [
        ("2L", "de 2 litros", 32900), ("20L", "de espalda de 20 litros", 189900)]),
    ("CPI", "Cepillo para piso", "unidad", "Jardín y aseo", "cepillo|piso|cerdas|restregar", [
        ("DUR", "cerdas duras con palo", 12900)]),
    # Cerrajería
    ("CSO", "Cerradura de sobreponer", "unidad", "Cerrajería", "cerradura|sobreponer|puerta|seguridad|chapa", [
        ("STD", "de seguridad para puerta principal", 89900)]),
    ("CHM", "Chapa para mueble", "unidad", "Cerrajería", "chapa|mueble|cajon|gaveta", [("22", "22 mm", 9900)]),
    ("MNJ", "Manija para puerta", "unidad", "Cerrajería", "manija|puerta|tirador|halador", [
        ("NIQ", "níquel satinado", 17900), ("NEG", "negra", 17900)]),
    ("MIR", "Mirilla para puerta", "unidad", "Cerrajería", "mirilla|ojo magico|puerta|visor", [("200", "200 grados", 14900)]),
    # Eléctricos
    ("TIM", "Timbre inalámbrico", "unidad", "Eléctricos", "timbre|inalambrico|campana|puerta", [("STD", "con pulsador", 39900)]),
    ("SEN", "Sensor de movimiento", "unidad", "Eléctricos", "sensor|movimiento|presencia|luz", [("TEC", "para techo", 34900)]),
    ("CLV", "Clavija", "unidad", "Eléctricos", "clavija|enchufe|macho", [("2P", "de 2 patas", 2900), ("3P", "de 3 patas", 4900)]),
    ("LIN", "Linterna recargable LED", "unidad", "Eléctricos", "linterna|recargable|led|lampara", [
        ("MAN", "de mano", 29900), ("CAB", "de cabeza", 24900)]),
    # Herramientas manuales
    ("TJL", "Tijera para lata", "unidad", "Herramientas manuales", "tijera|lata|lamina|cortar", [("10", "10 pulgadas", 34900)]),
    ("CNC", "Cincel plano", "unidad", "Herramientas manuales", "cincel|cortafrio|plano", [("34", "3/4 x 8 pulgadas", 15900)]),
    ("ESD", "Escuadra metálica", "unidad", "Herramientas manuales", "escuadra|metalica|carpintero", [("12", "12 pulgadas", 16900)]),
    ("CAU", "Cautín eléctrico", "unidad", "Herramientas manuales", "cautin|soldador|estaño", [
        ("40", "40 W", 18900), ("60", "60 W", 22900)]),
    ("PRE", "Prensa en C", "unidad", "Herramientas manuales", "prensa|sargento|sujetar", [
        ("4", "4 pulgadas", 17900), ("6", "6 pulgadas", 24900)]),
    # Seguridad industrial
    ("PAU", "Protector auditivo", "unidad", "Seguridad industrial", "protector|auditivo|oidos|ruido", [
        ("COP", "tipo copa", 24900), ("TAP", "tapones con cordón", 2900)]),
    ("CRT", "Careta para soldar", "unidad", "Seguridad industrial", "careta|soldar|mascara", [
        ("FIJ", "visor fijo", 29900)]),
    # Plomería
    ("TNQ", "Tanque de agua plástico", "unidad", "Plomería", "tanque|agua|plastico|reserva", [
        ("500", "500 litros", 329900), ("1000", "1.000 litros", 489900)]),
    ("FLO", "Flotador para tanque", "unidad", "Plomería", "flotador|tanque|boya|llenado", [("12", "1/2 pulgada", 21900)]),
    ("LLV", "Llave para lavadora", "unidad", "Plomería", "llave|lavadora|grifo|conexion", [("12", "1/2 pulgada", 16900)]),
    # Obra gris
    ("POL", "Polisombra negra", "metro", "Obra gris", "polisombra|sombra|malla|vivero", [("80", "80 % de 4 m de ancho", 6900)]),
    ("ADO", "Adoquín de concreto", "unidad", "Obra gris", "adoquin|piso|concreto|patio", [("RGR", "rectangular gris", 1900)]),
    # Pinturas y acabados
    ("BAR", "Barniz para madera", "unidad", "Pinturas y acabados", "barniz|madera|brillante|laca", [
        ("14", "1/4 de galón", 29900), ("1G", "galón", 89900)]),
    ("AER", "Aerosol esmalte", "unidad", "Pinturas y acabados", "aerosol|spray|esmalte", [
        ("NEG", "negro 300 ml", 14900), ("BLA", "blanco 300 ml", 14900), ("ROJ", "rojo 300 ml", 14900)]),
]
