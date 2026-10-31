"""Inventario 100 % ficticio de una ferretería de barrio colombiana para el catálogo de demostración.

Cada familia comparte nombre, unidad de venta, categoría y términos de búsqueda; sus variantes cambian la
medida o la presentación. Las existencias salen de una regla fija para que la base sea reproducible.
Restricciones para no cambiar el sentido de los casos de S2: no hay taladros ni herramientas «20 V», el tubo
PVC de presión para agua solo existe en 1/2 y 3/4 de pulgada, y las seis filas originales no cambian.
"""

import hashlib


# Filas del corte S2: precio y existencias fijos porque la evidencia y las pruebas dependen de ellos.
LEGACY = [
    ("PVC-050", "Tubo PVC presión para agua", "1/2 pulgada", "metro", 8500, 12, "tubo|tuberia|pvc|agua|media pulgada", "Plomería"),
    ("PVC-075", "Tubo PVC presión para agua", "3/4 pulgada", "metro", 11500, 7, "tubo|tuberia|pvc|agua|tres cuartos", "Plomería"),
    ("TOR-025-1", "Tornillo para madera", "1/4 x 1 pulgada", "unidad", 350, 80, "tornillo|madera|tirafondo", "Tornillería y fijación"),
    ("TOR-025-2", "Tornillo para madera", "1/4 x 2 pulgadas", "unidad", 520, 0, "tornillo|madera|tirafondo", "Tornillería y fijación"),
    ("CEM-050", "Cemento gris", "bulto de 50 kg", "bulto", 39500, 9, "cemento|gris|mezcla|bulto", "Obra gris"),
    ("PIN-BLA", "Pintura blanca vinilo", "galón", "galón", 56000, 4, "pintura|blanca|vinilo|galon", "Pinturas y acabados"),
]

# (prefijo, nombre, unidad, categoría, términos, [(código, variante, precio COP)])
FAMILIES = [
    # Plomería
    ("CPV", "Tubo CPVC para agua caliente", "metro", "Plomería", "tubo|tuberia|cpvc|agua caliente", [
        ("050", "1/2 pulgada", 12900), ("075", "3/4 pulgada", 17500)]),
    ("SAN", "Tubo PVC sanitario", "metro", "Plomería", "tubo|tuberia|pvc|sanitario|desague|alcantarillado", [
        ("2", "2 pulgadas", 9800), ("3", "3 pulgadas", 14500), ("4", "4 pulgadas", 19900), ("6", "6 pulgadas", 38500)]),
    ("CON", "Tubo PVC conduit eléctrico", "metro", "Eléctricos", "tubo|tuberia|pvc|conduit|electrico|cableado", [
        ("050", "1/2 pulgada", 3900), ("075", "3/4 pulgada", 5200), ("100", "1 pulgada", 7600)]),
    ("COD", "Codo PVC presión 90 grados", "unidad", "Plomería", "codo|pvc|accesorio|agua", [
        ("050", "1/2 pulgada", 1100), ("075", "3/4 pulgada", 1700), ("100", "1 pulgada", 3200)]),
    ("C45", "Codo PVC presión 45 grados", "unidad", "Plomería", "codo|pvc|accesorio|agua", [
        ("050", "1/2 pulgada", 1300), ("075", "3/4 pulgada", 1900)]),
    ("TEE", "Tee PVC presión", "unidad", "Plomería", "tee|te|pvc|accesorio|agua", [
        ("050", "1/2 pulgada", 1400), ("075", "3/4 pulgada", 2100), ("100", "1 pulgada", 3900)]),
    ("UNI", "Unión PVC presión", "unidad", "Plomería", "union|pvc|accesorio|agua", [
        ("050", "1/2 pulgada", 900), ("075", "3/4 pulgada", 1300)]),
    ("ADM", "Adaptador macho PVC", "unidad", "Plomería", "adaptador|macho|pvc|accesorio|rosca", [
        ("050", "1/2 pulgada", 1000), ("075", "3/4 pulgada", 1500)]),
    ("ADH", "Adaptador hembra PVC", "unidad", "Plomería", "adaptador|hembra|pvc|accesorio|rosca", [
        ("050", "1/2 pulgada", 1100), ("075", "3/4 pulgada", 1600)]),
    ("TAP", "Tapón PVC roscado", "unidad", "Plomería", "tapon|pvc|accesorio|rosca", [
        ("050", "1/2 pulgada", 700), ("075", "3/4 pulgada", 950)]),
    ("REG", "Registro de bola", "unidad", "Plomería", "registro|llave de paso|bola|agua|valvula", [
        ("050", "1/2 pulgada", 18900), ("075", "3/4 pulgada", 26500), ("100", "1 pulgada", 39900)]),
    ("LLT", "Llave terminal para jardín", "unidad", "Plomería", "llave|terminal|grifo|jardin|agua", [
        ("050", "1/2 pulgada", 15900)]),
    ("SOL", "Soldadura líquida PVC", "unidad", "Plomería", "soldadura|pegante|pvc|tubo", [
        ("132", "1/32 de galón", 9800), ("018", "1/8 de galón", 24900), ("014", "1/4 de galón", 42900)]),
    ("LIM", "Limpiador PVC", "unidad", "Plomería", "limpiador|removedor|pvc", [("132", "1/32 de galón", 7900)]),
    ("TEF", "Cinta teflón", "rollo", "Plomería", "teflon|cinta|sellar|rosca", [
        ("012", "1/2 pulgada x 10 m", 1500), ("034", "3/4 pulgada x 15 m", 2900)]),
    ("MAB", "Manguera de abasto", "unidad", "Plomería", "manguera|abasto|lavamanos|sanitario|flexible", [
        ("40", "1/2 x 40 cm", 9900), ("60", "1/2 x 60 cm", 11900)]),
    ("SIF", "Sifón para lavaplatos", "unidad", "Plomería", "sifon|lavaplatos|desague|plastico", [
        ("112", "1 1/2 pulgada", 12900)]),
    ("DUC", "Ducha eléctrica", "unidad", "Plomería", "ducha|electrica|calentador|baño", [
        ("3T", "3 temperaturas", 69900)]),
    # Obra gris
    ("CEM", "Cemento gris", "bulto", "Obra gris", "cemento|gris|mezcla|bulto", [("025", "bulto de 25 kg", 22500)]),
    ("CBL", "Cemento blanco", "bolsa", "Obra gris", "cemento|blanco|boquilla|bolsa", [
        ("001", "bolsa de 1 kg", 4900), ("005", "bolsa de 5 kg", 19900)]),
    ("MOR", "Mortero seco", "bulto", "Obra gris", "mortero|pega|ladrillo|bulto|mezcla", [("040", "bulto de 40 kg", 24900)]),
    ("PGC", "Pegante para cerámica", "bulto", "Obra gris", "pegante|pegacor|ceramica|baldosa|bulto", [
        ("GR25", "gris bulto de 25 kg", 23900), ("BL25", "blanco bulto de 25 kg", 31900)]),
    ("BOQ", "Boquilla para cerámica", "bolsa", "Obra gris", "boquilla|ceramica|junta|bolsa", [
        ("BLA", "blanca bolsa de 2 kg", 7900), ("GRI", "gris bolsa de 2 kg", 7900), ("NEG", "negra bolsa de 2 kg", 8900),
        ("BEI", "beige bolsa de 2 kg", 8400)]),
    ("CAL", "Cal hidratada", "bulto", "Obra gris", "cal|hidratada|bulto|mezcla", [("025", "bulto de 25 kg", 18500)]),
    ("ARE", "Arena de río lavada", "bulto", "Obra gris", "arena|rio|bulto|mezcla", [("040", "bulto de 40 kg", 6500)]),
    ("GRV", "Gravilla", "bulto", "Obra gris", "gravilla|triturado|piedra|bulto", [("040", "bulto de 40 kg", 7500)]),
    ("YES", "Yeso", "bulto", "Obra gris", "yeso|bulto|acabado", [("025", "bulto de 25 kg", 21900)]),
    ("EST", "Estuco plástico", "unidad", "Obra gris", "estuco|masilla|pared|acabado", [
        ("GAL", "galón", 29900), ("CUN", "cuñete de 5 galones", 119900)]),
    ("IMP", "Impermeabilizante para techos", "unidad", "Obra gris", "impermeabilizante|techo|terraza|goteras", [
        ("GAL", "galón", 64900), ("CUN", "cuñete de 5 galones", 289900)]),
    ("VAR", "Varilla corrugada", "unidad", "Obra gris", "varilla|hierro|acero|corrugada|construccion", [
        ("014", "1/4 x 6 m", 9900), ("038", "3/8 x 6 m", 19900), ("012", "1/2 x 6 m", 34900)]),
    ("ALA", "Alambre negro recocido", "rollo", "Obra gris", "alambre|negro|amarrar|recocido", [("001", "rollo de 1 kg", 8900)]),
    ("MAL", "Malla electrosoldada", "unidad", "Obra gris", "malla|electrosoldada|placa|construccion", [
        ("M4", "6 x 2.35 m calibre 4 mm", 98000)]),
    ("LAD", "Ladrillo tolete", "unidad", "Obra gris", "ladrillo|tolete|muro", [("COM", "común", 950)]),
    ("BLQ", "Bloque de concreto", "unidad", "Obra gris", "bloque|concreto|muro", [
        ("010", "10 cm", 2400), ("015", "15 cm", 2900)]),
    # Tornillería y fijación
    ("TOR", "Tornillo para madera", "unidad", "Tornillería y fijación", "tornillo|madera|tirafondo", [
        ("025-3", "1/4 x 3 pulgadas", 690), ("316-1", "3/16 x 1 pulgada", 250), ("316-2", "3/16 x 2 pulgadas", 380)]),
    ("TDR", "Tornillo drywall", "unidad", "Tornillería y fijación", "tornillo|drywall|superboard|punta broca", [
        ("6-1", "#6 x 1 pulgada", 90), ("6-158", "#6 x 1 5/8 pulgada", 120), ("8-2", "#8 x 2 pulgadas", 180)]),
    ("TAU", "Tornillo autoperforante", "unidad", "Tornillería y fijación", "tornillo|autoperforante|lamina|goloso|teja", [
        ("10-1", "#10 x 1 pulgada", 210), ("12-2", "#12 x 2 pulgadas", 390)]),
    ("CHZ", "Chazo plástico", "unidad", "Tornillería y fijación", "chazo|taco|anclaje|pared", [
        ("014", "1/4 pulgada", 80), ("516", "5/16 pulgada", 120), ("038", "3/8 pulgada", 160)]),
    ("PER", "Perno hexagonal galvanizado", "unidad", "Tornillería y fijación", "perno|hexagonal|galvanizado|tuerca", [
        ("014-2", "1/4 x 2 pulgadas", 900), ("038-3", "3/8 x 3 pulgadas", 1800), ("012-4", "1/2 x 4 pulgadas", 3500)]),
    ("TUE", "Tuerca hexagonal", "unidad", "Tornillería y fijación", "tuerca|hexagonal|galvanizada", [
        ("014", "1/4 pulgada", 150), ("038", "3/8 pulgada", 250), ("012", "1/2 pulgada", 450)]),
    ("ARA", "Arandela plana", "unidad", "Tornillería y fijación", "arandela|guasa|plana", [
        ("014", "1/4 pulgada", 60), ("038", "3/8 pulgada", 90)]),
    ("PUN", "Puntilla con cabeza", "libra", "Tornillería y fijación", "puntilla|clavo|cabeza", [
        ("1", "1 pulgada", 4200), ("112", "1 1/2 pulgada", 4000), ("2", "2 pulgadas", 3900), ("3", "3 pulgadas", 3900)]),
    ("PAC", "Puntilla de acero", "caja", "Tornillería y fijación", "puntilla|clavo|acero|concreto", [
        ("1", "caja de 100 unidades 1 pulgada", 8900), ("2", "caja de 100 unidades 2 pulgadas", 11900)]),
    ("GRA", "Grapa para cerca", "libra", "Tornillería y fijación", "grapa|cerca|alambre|puas", [("1", "1 pulgada", 6900)]),
    # Herramientas manuales
    ("MAR", "Martillo de uña", "unidad", "Herramientas manuales", "martillo|uña|carpintero", [
        ("16", "16 oz", 24900), ("20", "20 oz", 32900)]),
    ("MAC", "Maceta de acero", "unidad", "Herramientas manuales", "maceta|porra|mazo", [("2LB", "2 lb", 29900), ("4LB", "4 lb", 42900)]),
    ("ALI", "Alicate universal", "unidad", "Herramientas manuales", "alicate|pinza|universal", [
        ("6", "6 pulgadas", 17900), ("8", "8 pulgadas", 22900)]),
    ("PIC", "Pinza de punta", "unidad", "Herramientas manuales", "pinza|punta|alicate", [("6", "6 pulgadas", 16900)]),
    ("COR", "Cortafrío diagonal", "unidad", "Herramientas manuales", "cortafrio|diagonal|cortar cable", [("6", "6 pulgadas", 18900)]),
    ("DPA", "Destornillador de pala", "unidad", "Herramientas manuales", "destornillador|pala|plano|atornillador", [
        ("14-4", "1/4 x 4 pulgadas", 7900), ("516-6", "5/16 x 6 pulgadas", 9900)]),
    ("DES", "Destornillador de estrella", "unidad", "Herramientas manuales", "destornillador|estrella|phillips|atornillador", [
        ("1-3", "#1 x 3 pulgadas", 7500), ("2-4", "#2 x 4 pulgadas", 8500)]),
    ("LLE", "Llave expansiva", "unidad", "Herramientas manuales", "llave|expansiva|inglesa|ajustable", [
        ("8", "8 pulgadas", 24900), ("10", "10 pulgadas", 31900), ("12", "12 pulgadas", 39900)]),
    ("LLA", "Llave para tubo", "unidad", "Herramientas manuales", "llave|tubo|stillson|plomeria", [
        ("14", "14 pulgadas", 48900), ("18", "18 pulgadas", 69900)]),
    ("FLX", "Flexómetro", "unidad", "Herramientas manuales", "flexometro|metro|cinta metrica|medir", [
        ("3", "3 m", 9900), ("5", "5 m", 15900), ("8", "8 m", 24900)]),
    ("NIV", "Nivel de burbuja", "unidad", "Herramientas manuales", "nivel|burbuja|aluminio", [
        ("12", "12 pulgadas", 16900), ("24", "24 pulgadas", 29900)]),
    ("SEG", "Arco de segueta", "unidad", "Herramientas manuales", "segueta|arco|sierra|metal", [("12", "12 pulgadas", 21900)]),
    ("HSE", "Hoja de segueta", "unidad", "Abrasivos y corte", "hoja|segueta|sierra|metal|repuesto", [
        ("18", "18 dientes", 3900), ("24", "24 dientes", 3900)]),
    ("SER", "Serrucho", "unidad", "Herramientas manuales", "serrucho|madera|sierra", [("20", "20 pulgadas", 29900)]),
    ("PAL", "Pala cuadrada", "unidad", "Herramientas manuales", "pala|cuadrada|obra|arena", [("MAD", "mango de madera", 39900)]),
    ("PIK", "Pica con mango", "unidad", "Herramientas manuales", "pica|zapapico|excavar", [("5LB", "5 lb", 49900)]),
    ("PLU", "Palustre", "unidad", "Herramientas manuales", "palustre|cuchara|albañil", [("7", "7 pulgadas", 13900), ("9", "9 pulgadas", 16900)]),
    ("LLN", "Llana metálica", "unidad", "Herramientas manuales", "llana|metalica|pañete|estuco", [
        ("LIS", "lisa", 15900), ("DEN", "dentada", 16900)]),
    ("CAR", "Carretilla", "unidad", "Herramientas manuales", "carretilla|buggy|obra", [("90", "90 litros llanta neumática", 189000)]),
    ("ESP", "Espátula", "unidad", "Herramientas manuales", "espatula|raspar|masilla", [
        ("2", "2 pulgadas", 5900), ("3", "3 pulgadas", 6900), ("4", "4 pulgadas", 7900)]),
    # Pinturas y acabados
    ("PIN", "Pintura blanca vinilo", "unidad", "Pinturas y acabados", "pintura|blanca|vinilo|pared", [
        ("BLA-14", "1/4 de galón", 17900), ("BLA-C5", "cuñete de 5 galones", 239000)]),
    *[
        ("PIV", f"Pintura vinilo {color}", "unidad", "Pinturas y acabados", f"pintura|vinilo|{color}|pared", [
            (f"{code}-G", "galón", price), (f"{code}-14", "1/4 de galón", round(price * 0.32, -2))])
        for code, color, price in (
            ("BEI", "beige", 58900), ("GRI", "gris", 58900), ("AMA", "amarilla", 61900), ("AZU", "azul", 61900),
            ("VER", "verde", 61900), ("ROJ", "roja", 63900), ("NEG", "negra", 59900), ("MAR", "marfil", 58900),
        )
    ],
    *[
        ("ESM", f"Esmalte sintético {color}", "unidad", "Pinturas y acabados", f"esmalte|sintetico|aceite|{color}|reja|puerta", [
            (f"{code}-G", "galón", price), (f"{code}-14", "1/4 de galón", round(price * 0.3, -2))])
        for code, color, price in (
            ("BLA", "blanco", 79900), ("NEG", "negro", 79900), ("GRI", "gris", 81900), ("ROJ", "rojo", 84900),
            ("VER", "verde", 84900), ("AZU", "azul", 84900),
        )
    ],
    ("ANT", "Anticorrosivo", "unidad", "Pinturas y acabados", "anticorrosivo|base|metal|oxido", [
        ("GRI-G", "gris galón", 69900), ("ROJ-G", "rojo galón", 69900), ("GRI-14", "gris 1/4 de galón", 21900)]),
    ("THI", "Thinner", "unidad", "Pinturas y acabados", "thinner|disolvente|diluyente", [
        ("750", "botella de 750 ml", 8900), ("GAL", "galón", 29900)]),
    ("VRS", "Varsol", "unidad", "Pinturas y acabados", "varsol|disolvente|limpiar brochas", [
        ("750", "botella de 750 ml", 7900), ("GAL", "galón", 25900)]),
    ("SEL", "Sellador para madera", "unidad", "Pinturas y acabados", "sellador|madera|laca|base", [
        ("GAL", "galón", 74900), ("14", "1/4 de galón", 23900)]),
    ("BRO", "Brocha de cerda", "unidad", "Pinturas y acabados", "brocha|pincel|pintar", [
        ("1", "1 pulgada", 2900), ("2", "2 pulgadas", 4900), ("3", "3 pulgadas", 6900), ("4", "4 pulgadas", 8900)]),
    ("ROD", "Rodillo de felpa", "unidad", "Pinturas y acabados", "rodillo|felpa|pintar", [
        ("9", "9 pulgadas", 13900), ("4", "4 pulgadas", 7900)]),
    ("BAN", "Bandeja para pintura", "unidad", "Pinturas y acabados", "bandeja|rodillo|pintura", [("9", "9 pulgadas", 6900)]),
    ("CEN", "Cinta de enmascarar", "rollo", "Pinturas y acabados", "cinta|enmascarar|pintor|papel", [
        ("034", "3/4 pulgada x 40 m", 4900), ("1", "1 pulgada x 40 m", 6500), ("2", "2 pulgadas x 40 m", 11900)]),
    ("LIJ", "Lija de agua", "pliego", "Abrasivos y corte", "lija|agua|pliego|lijar", [
        ("080", "grano 80", 1900), ("100", "grano 100", 1900), ("150", "grano 150", 1900), ("220", "grano 220", 1900),
        ("400", "grano 400", 2100)]),
    ("DIS", "Disco de corte", "unidad", "Abrasivos y corte", "disco|corte|pulidora", [
        ("MET", "metal 4 1/2 pulgadas", 4900), ("CON", "concreto 4 1/2 pulgadas", 6900), ("DIA", "diamantado 4 1/2 pulgadas", 24900)]),
    ("BRC", "Broca para concreto", "unidad", "Abrasivos y corte", "broca|concreto|pared|widia", [
        ("014", "1/4 pulgada", 4900), ("516", "5/16 pulgada", 5900), ("038", "3/8 pulgada", 7900)]),
    ("BRM", "Broca para metal", "unidad", "Abrasivos y corte", "broca|metal|acero", [
        ("018", "1/8 pulgada", 2900), ("316", "3/16 pulgada", 3900), ("014", "1/4 pulgada", 4900)]),
    # Eléctricos
    *[
        ("CAB", f"Cable eléctrico THHN calibre {gauge} AWG", "metro", "Eléctricos", "cable|electrico|thhn|alambre|cobre", [
            (f"{gauge}-{code}", color, price) for code, color in (("BL", "blanco"), ("NE", "negro"), ("RO", "rojo"), ("VE", "verde"))])
        for gauge, price in ((14, 1900), (12, 2700), (10, 4200))
    ],
    ("DUP", "Cable dúplex encauchetado", "metro", "Eléctricos", "cable|duplex|encauchetado|extension", [
        ("2X16", "2 x 16 AWG", 2900), ("2X14", "2 x 14 AWG", 3900)]),
    ("INT", "Interruptor", "unidad", "Eléctricos", "interruptor|suiche|switch|luz", [
        ("SEN", "sencillo", 6900), ("DOB", "doble", 10900), ("CON", "conmutable", 9900)]),
    ("TOM", "Toma corriente", "unidad", "Eléctricos", "toma|enchufe|tomacorriente", [
        ("DOB", "doble", 6900), ("TIE", "doble con polo a tierra", 9900), ("GFC", "GFCI para baño", 49900)]),
    ("BOM", "Bombillo LED", "unidad", "Eléctricos", "bombillo|led|foco|luz", [
        ("09", "9 W luz blanca", 5900), ("12", "12 W luz blanca", 7900), ("15", "15 W luz blanca", 9900),
        ("09C", "9 W luz cálida", 6200)]),
    ("PLA", "Plafón de porcelana", "unidad", "Eléctricos", "plafon|roseta|porcelana|bombillo", [("STD", "estándar", 3900)]),
    ("CIN", "Cinta aislante", "rollo", "Eléctricos", "cinta|aislante|electrica", [
        ("NEG", "negra 18 m", 3500), ("ROJ", "roja 18 m", 3900)]),
    ("EXT", "Extensión eléctrica", "unidad", "Eléctricos", "extension|cable|enchufe", [
        ("3", "3 m", 14900), ("5", "5 m", 19900), ("10", "10 m", 32900)]),
    ("MUL", "Multitoma con protección", "unidad", "Eléctricos", "multitoma|regleta|protector", [("6", "6 salidas", 29900)]),
    ("BRK", "Breaker enchufable", "unidad", "Eléctricos", "breaker|taco|automatico|tablero", [
        ("15", "1 polo 15 A", 15900), ("20", "1 polo 20 A", 15900), ("30", "1 polo 30 A", 16900), ("2P40", "2 polos 40 A", 42900)]),
    ("CAJ", "Caja de paso PVC", "unidad", "Eléctricos", "caja|paso|electrica|empalme", [
        ("2X4", "2 x 4 pulgadas", 1200), ("4X4", "4 x 4 pulgadas", 2100)]),
    # Cerrajería
    ("CAN", "Candado de latón", "unidad", "Cerrajería", "candado|laton|seguridad", [
        ("30", "30 mm", 14900), ("40", "40 mm", 21900), ("50", "50 mm", 29900)]),
    ("CER", "Cerradura de pomo", "unidad", "Cerrajería", "cerradura|chapa|pomo|puerta", [
        ("ALC", "alcoba", 34900), ("BAN", "baño", 32900), ("ENT", "entrada con llave", 49900)]),
    ("BIS", "Bisagra de cobre", "par", "Cerrajería", "bisagra|puerta|cobre", [
        ("3", "3 pulgadas", 6900), ("312", "3 1/2 pulgadas", 7900), ("4", "4 pulgadas", 9900)]),
    ("PAS", "Pasador de sobreponer", "unidad", "Cerrajería", "pasador|picaporte|seguro|puerta", [
        ("3", "3 pulgadas", 4900), ("4", "4 pulgadas", 5900)]),
    ("CAD", "Cadena galvanizada", "metro", "Cerrajería", "cadena|galvanizada|eslabon", [
        ("3MM", "3 mm", 3900), ("5MM", "5 mm", 6900)]),
    # Adhesivos y sellantes
    ("SIL", "Silicona acética", "unidad", "Adhesivos y sellantes", "silicona|sellante|acetica|cartucho", [
        ("TRA", "transparente cartucho de 280 ml", 13900), ("BLA", "blanca cartucho de 280 ml", 13900)]),
    ("PIS", "Pistola para silicona", "unidad", "Adhesivos y sellantes", "pistola|silicona|cartucho|calafateo", [("STD", "estándar", 12900)]),
    ("PCO", "Pegante de contacto", "unidad", "Adhesivos y sellantes", "pegante|contacto|boxer|zapatero", [
        ("18", "1/8 de galón", 15900), ("14", "1/4 de galón", 27900)]),
    ("PMA", "Pegante para madera", "unidad", "Adhesivos y sellantes", "pegante|colbon|madera|carpintero", [
        ("250", "frasco de 250 g", 6900), ("GAL", "galón", 39900)]),
    ("EPO", "Masilla epóxica", "unidad", "Adhesivos y sellantes", "masilla|epoxica|soldadura en frio", [("50", "50 g", 9900)]),
    ("ESX", "Espuma expansiva", "unidad", "Adhesivos y sellantes", "espuma|expansiva|poliuretano|sellar", [("500", "500 ml", 24900)]),
    # Jardín y aseo
    ("MAN", "Manguera para jardín", "unidad", "Jardín y aseo", "manguera|jardin|riego|agua", [
        ("12-15", "1/2 pulgada x 15 m", 34900), ("12-25", "1/2 pulgada x 25 m", 52900)]),
    ("ESC", "Escoba plástica", "unidad", "Jardín y aseo", "escoba|barrer|aseo", [("STD", "con palo", 9900)]),
    ("REC", "Recogedor", "unidad", "Jardín y aseo", "recogedor|pala de basura|aseo", [("STD", "con mango", 6900)]),
    ("BAL", "Balde plástico", "unidad", "Jardín y aseo", "balde|cubeta|tarro", [("12", "12 litros", 7900), ("20", "20 litros", 12900)]),
    ("TIJ", "Tijera podadora", "unidad", "Jardín y aseo", "tijera|podar|jardin", [("8", "8 pulgadas", 24900)]),
    # Seguridad industrial
    ("GUA", "Guantes de carnaza", "par", "Seguridad industrial", "guantes|carnaza|proteccion|trabajo", [
        ("M", "talla M", 8900), ("L", "talla L", 8900)]),
    ("GNI", "Guantes de nitrilo", "par", "Seguridad industrial", "guantes|nitrilo|quimicos|proteccion", [("M", "talla M", 6900)]),
    ("GAF", "Gafas de seguridad", "unidad", "Seguridad industrial", "gafas|monogafas|proteccion|ojos", [
        ("CLA", "lente claro", 6900), ("OSC", "lente oscuro", 7900)]),
    ("TPB", "Tapabocas", "unidad", "Seguridad industrial", "tapabocas|mascarilla|polvo", [("N95", "N95", 4900)]),
    ("CAS", "Casco de seguridad", "unidad", "Seguridad industrial", "casco|proteccion|obra", [("BLA", "blanco", 24900), ("AMA", "amarillo", 24900)]),
]


def _fraction_code(value: str) -> str:
    return value.replace(" ", "").replace("/", "")


# Familias combinatorias: medidas habituales en mostrador, para que el catálogo se parezca a uno real.
FAMILIES += [
    ("PRH", "Perno hexagonal grado 5", "unidad", "Tornillería y fijación", "perno|hexagonal|grado 5|tuerca", [
        (f"{_fraction_code(d)}-{length}", f"{d} x {length} pulgada{'s' if length > 1 else ''}",
         round(price * (1 + length / 3) / 50) * 50)
        for d, price in (("1/4", 700), ("5/16", 950), ("3/8", 1300), ("1/2", 2400)) for length in (1, 2, 3, 4)]),
    ("TLA", "Tornillo para lámina", "unidad", "Tornillería y fijación", "tornillo|lamina|metal|goloso", [
        (f"{n}-{_fraction_code(length)}", f"#{n} x {length} pulgada", price)
        for n, length, price in ((8, "1/2", 60), (8, "3/4", 70), (8, "1", 80), (10, "1", 110), (10, "1 1/2", 140))]),
    ("BRD", "Broca para madera", "unidad", "Abrasivos y corte", "broca|madera|paleta|carpinteria", [
        (_fraction_code(size), f"{size} pulgada", price)
        for size, price in (("1/4", 5900), ("3/8", 7900), ("1/2", 9900), ("3/4", 13900))]),
    ("BRX", "Broca para concreto larga", "unidad", "Abrasivos y corte", "broca|concreto|larga|pared", [
        (_fraction_code(size), f"{size} x 6 pulgadas", price)
        for size, price in (("1/8", 5900), ("3/16", 6900), ("1/4", 7900), ("1/2", 15900))]),
    ("LED", "Bombillo LED ahorrador", "unidad", "Eléctricos", "bombillo|led|foco|luz|ahorrador", [
        (f"{watts}{tone[0].upper()}", f"{watts} W luz {tone}", 3000 + watts * 350)
        for watts in (7, 18, 20, 30) for tone in ("blanca", "cálida")]),
    ("REF", "Reflector LED exterior", "unidad", "Eléctricos", "reflector|led|exterior|lampara", [
        (str(watts), f"{watts} W", 12000 + watts * 450) for watts in (30, 50, 100, 150)]),
    ("CAB", "Cable eléctrico THHN calibre 8 AWG", "metro", "Eléctricos", "cable|electrico|thhn|alambre|cobre", [
        ("8-NE", "negro", 6900), ("8-BL", "blanco", 6900), ("8-VE", "verde", 6900)]),
    ("ENC", "Cable encauchetado", "metro", "Eléctricos", "cable|encauchetado|vulcanizado|extension", [
        ("3X12", "3 x 12 AWG", 8900), ("3X14", "3 x 14 AWG", 6400), ("2X12", "2 x 12 AWG", 6900)]),
    ("RED", "Reducción PVC presión", "unidad", "Plomería", "reduccion|buje|pvc|accesorio|agua", [
        ("075-050", "3/4 a 1/2 pulgada", 1200), ("100-075", "1 a 3/4 pulgada", 1900), ("100-050", "1 a 1/2 pulgada", 1900)]),
    ("CSN", "Codo PVC sanitario", "unidad", "Plomería", "codo|sanitario|pvc|desague", [
        (str(size), f"{size} pulgadas", price) for size, price in ((2, 2900), (3, 5400), (4, 8900))]),
    ("YSN", "Yee PVC sanitaria", "unidad", "Plomería", "yee|sanitaria|pvc|desague", [
        (str(size), f"{size} pulgadas", price) for size, price in ((2, 4900), (3, 8900), (4, 13900))]),
    ("REJ", "Rejilla de piso con sosco", "unidad", "Plomería", "rejilla|sosco|piso|desague|ducha", [
        ("2", "2 pulgadas", 6900), ("3", "3 pulgadas", 8900)]),
    ("GRL", "Grifo para lavamanos", "unidad", "Plomería", "grifo|llave|lavamanos|griferia", [
        ("SEN", "sencillo cromado", 39900), ("PUL", "pulsador ahorrador", 59900)]),
    ("GLP", "Grifo para lavaplatos", "unidad", "Plomería", "grifo|llave|lavaplatos|cocina|griferia", [
        ("CUE", "cuello de ganso", 64900), ("PAR", "de pared", 45900)]),
    ("VLL", "Válvula de llenado para sanitario", "unidad", "Plomería", "valvula|llenado|tanque|sanitario|flotador", [
        ("UNI", "universal", 24900)]),
    ("PIV", "Pintura vinilo", "unidad", "Pinturas y acabados", "pintura|vinilo|pared|cuñete", [
        (f"{code}-C5", f"{color} cuñete de 5 galones", price)
        for code, color, price in (("BEI", "beige", 249000), ("GRI", "gris", 249000), ("MAR", "marfil", 249000))]),
    ("LMA", "Lija para madera", "pliego", "Abrasivos y corte", "lija|madera|pliego|lijar", [
        (f"M{grit}", f"grano {grit}", 1500) for grit in (60, 80, 120, 180)]),
    ("LJM", "Lija para metal", "pliego", "Abrasivos y corte", "lija|metal|tela|esmeril", [
        (str(grit), f"grano {grit}", 2400) for grit in (36, 60, 80, 120)]),
    ("JLL", "Juego de llaves combinadas", "unidad", "Herramientas manuales", "juego|llaves|combinadas|mixtas", [
        ("MET", "métricas de 8 a 19 mm, 8 piezas", 59900), ("STD", "estándar de 1/4 a 3/4 pulgada, 8 piezas", 59900)]),
    ("ALN", "Juego de llaves Allen", "unidad", "Herramientas manuales", "llaves|allen|hexagonales|juego", [
        ("MET", "métricas 9 piezas", 18900), ("STD", "estándar 9 piezas", 18900)]),
    ("TRI", "Triplex de pino", "unidad", "Maderas", "triplex|madera|lamina|pino", [
        (f"{mm}", f"{mm} mm 1,22 x 2,44 m", price) for mm, price in ((4, 42900), (9, 68900), (12, 84900), (15, 98900))]),
    ("LIS", "Listón de pino", "unidad", "Maderas", "liston|madera|pino|cepillado", [
        ("2X2", "2 x 2 pulgadas x 3 m", 13900), ("2X3", "2 x 3 pulgadas x 3 m", 18900), ("1X2", "1 x 2 pulgadas x 3 m", 7900)]),
    ("TZN", "Teja de zinc ondulada", "unidad", "Obra gris", "teja|zinc|techo|lamina", [
        (str(feet), f"{feet} pies calibre 34", 18000 + feet * 2600) for feet in (6, 8, 10, 12)]),
    ("TPL", "Teja plástica traslúcida", "unidad", "Obra gris", "teja|plastica|traslucida|techo", [
        (str(feet), f"{feet} pies", 22000 + feet * 3900) for feet in (6, 8, 10)]),
    ("ANG", "Ángulo de hierro", "unidad", "Obra gris", "angulo|hierro|perfil|soldadura", [
        ("1-8", "1 x 1/8 pulgada x 6 m", 44900), ("112-316", "1 1/2 x 3/16 pulgada x 6 m", 89900)]),
    ("PLN", "Plástico negro calibre 6", "metro", "Obra gris", "plastico|negro|polietileno|cubrir", [("2M", "2 m de ancho", 3900)]),
    ("BOT", "Botas de caucho", "par", "Seguridad industrial", "botas|caucho|pantaneras|obra", [
        (str(size), f"talla {size}", 39900) for size in range(37, 45)]),
    ("GUC", "Guantes de caucho", "par", "Seguridad industrial", "guantes|caucho|aseo|domesticos", [
        (size, f"talla {size}", 4900) for size in ("S", "M", "L", "XL")]),
    ("CHA", "Chaleco reflectivo", "unidad", "Seguridad industrial", "chaleco|reflectivo|seguridad|vial", [
        ("NAR", "naranja", 14900), ("VER", "verde limón", 14900)]),
    ("MNG", "Manguera para jardín reforzada", "unidad", "Jardín y aseo", "manguera|jardin|riego|reforzada", [
        ("34-15", "3/4 pulgada x 15 m", 54900), ("34-30", "3/4 pulgada x 30 m", 94900)]),
    ("ASP", "Aspersor de jardín", "unidad", "Jardín y aseo", "aspersor|riego|jardin|regadera", [
        ("CIR", "circular", 12900), ("OSC", "oscilante", 29900)]),
    ("TRP", "Trapero de algodón", "unidad", "Jardín y aseo", "trapero|mopa|aseo|piso", [("STD", "con palo", 11900)]),
]


def _stock(sku: str) -> int:
    # Existencias reproducibles: alrededor de 1 de cada 12 variantes queda agotada.
    digest = int(hashlib.sha256(sku.encode()).hexdigest(), 16)
    return 0 if digest % 12 == 0 else 1 + digest % 60


def build_products() -> list[tuple[str, str, str, str, int, int, str, str]]:
    """Filas (SKU, nombre, variante, unidad, precio, stock, términos, categoría), sin SKU repetidos."""
    rows = list(LEGACY)
    for prefix, name, unit, category, terms, variants in FAMILIES:
        for code, variant, price in variants:
            sku = f"{prefix}-{code}"
            rows.append((sku, name, variant, unit, int(price), _stock(sku), terms, category))
    skus = [row[0] for row in rows]
    if len(skus) != len(set(skus)):
        raise ValueError("SKU repetido en el catálogo de demostración.")
    return rows
