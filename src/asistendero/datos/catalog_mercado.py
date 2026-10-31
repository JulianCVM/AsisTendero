"""Inventario 100 % ficticio de una tienda de barrio colombiana de mercado diario (segundo negocio de demostración).

Sirve para evaluar al agente fuera de la ferretería: compras de la casa por libra, por unidad o por paquete,
productos frescos, aseo y mecato. Sin marcas: cada producto se nombra por lo que es. Los prefijos empiezan por «M»
y ninguno repite uno de la ferretería, que vive en la misma base con otro ``business_id`` (lo comprueba
``tests/test_mercado.py``): así un SKU nunca dice a qué negocio pertenece por accidente.
"""

MARKET_BUSINESS_ID = "demo-tienda-barrio"

# (prefijo, nombre, unidad, categoría, términos, [(código, variante, precio COP)])
MARKET_FAMILIES = [
    # Granos y abarrotes
    ("MARR", "Arroz blanco", "bolsa", "Granos y abarrotes", "arroz|blanco|grano|libra", [
        ("1LB", "1 libra", 2900), ("5LB", "5 libras", 13900)]),
    ("MLEN", "Lenteja", "bolsa", "Granos y abarrotes", "lenteja|lentejas|grano|menestra", [("1LB", "1 libra", 3900)]),
    ("MFRI", "Fríjol", "bolsa", "Granos y abarrotes", "frijol|frisol|frijoles|grano|menestra", [
        ("ROJ", "rojo 1 libra", 6900), ("CAR", "cargamanto 1 libra", 8900)]),
    ("MGAR", "Garbanzo", "bolsa", "Granos y abarrotes", "garbanzo|garbanzos|grano", [("1LB", "1 libra", 4900)]),
    ("MAZU", "Azúcar blanca", "bolsa", "Granos y abarrotes", "azucar|blanca|endulzar", [
        ("1LB", "1 libra", 2700), ("1KG", "1 kg", 5200)]),
    ("MSAL", "Sal refinada", "bolsa", "Granos y abarrotes", "sal|refinada|yodada", [("500", "500 g", 1600), ("1KG", "1 kg", 2800)]),
    ("MPAN", "Panela", "unidad", "Granos y abarrotes", "panela|dulce|aguapanela", [
        ("500", "pastilla de 500 g", 3200), ("PAR", "par de 1 kg", 6000)]),
    ("MACE", "Aceite vegetal", "botella", "Granos y abarrotes", "aceite|vegetal|cocina|freir", [
        ("500", "500 ml", 6900), ("1L", "1 litro", 12900), ("3L", "3 litros", 34900)]),
    ("MPAS", "Pasta espagueti", "paquete", "Granos y abarrotes", "pasta|espagueti|spaghetti|fideos", [
        ("250", "250 g", 2400), ("500", "500 g", 4300)]),
    ("MHAR", "Harina de maíz precocida", "paquete", "Granos y abarrotes", "harina|maiz|arepa|arepas|precocida", [
        ("500", "500 g", 3500), ("1KG", "1 kg", 6400)]),
    ("MHTR", "Harina de trigo", "paquete", "Granos y abarrotes", "harina|trigo|reposteria", [("500", "500 g", 2900)]),
    ("MAVE", "Avena en hojuelas", "bolsa", "Granos y abarrotes", "avena|hojuelas|desayuno", [("400", "400 g", 4200)]),
    ("MCAF", "Café molido", "paquete", "Granos y abarrotes", "cafe|tinto|molido", [
        ("125", "125 g", 5900), ("250", "250 g", 10900), ("500", "500 g", 19900)]),
    ("MCHO", "Chocolate de mesa", "paquete", "Granos y abarrotes", "chocolate|mesa|pastillas|desayuno", [
        ("250", "250 g", 6900), ("500", "500 g", 12900)]),
    ("MATU", "Atún en lata", "lata", "Granos y abarrotes", "atun|lata|enlatado", [
        ("ACE", "en aceite 170 g", 6400), ("AGU", "en agua 170 g", 6400)]),
    ("MSAR", "Sardinas en salsa de tomate", "lata", "Granos y abarrotes", "sardinas|lata|enlatado", [("425", "425 g", 7900)]),
    ("MFEC", "Fécula de maíz", "caja", "Granos y abarrotes", "fecula|maicena|colada", [("380", "380 g", 5400)]),
    # Lácteos y huevos
    ("MLEC", "Leche entera", "bolsa", "Lácteos y huevos", "leche|entera|bolsa", [("1L", "1 litro", 4300), ("900", "900 ml", 3900)]),
    ("MLDL", "Leche deslactosada", "unidad", "Lácteos y huevos", "leche|deslactosada|sin lactosa", [
        ("BOL", "bolsa de 1 litro", 4900), ("CAJ", "caja de 1 litro", 5900)]),
    ("MLPO", "Leche en polvo", "bolsa", "Lácteos y huevos", "leche|polvo|entera", [("400", "400 g", 15900)]),
    ("MHUE", "Huevo rojo AA", "unidad", "Lácteos y huevos", "huevo|huevos|rojo|aa", [("UNI", "por unidad", 650)]),
    ("MCUB", "Cubeta de huevos AA", "cubeta", "Lácteos y huevos", "huevo|huevos|cubeta|panal|aa", [("30", "30 huevos", 17900)]),
    ("MQUE", "Queso campesino", "unidad", "Lácteos y huevos", "queso|campesino|blanco", [
        ("MLB", "media libra", 6400), ("1LB", "1 libra", 12400)]),
    ("MMAN", "Mantequilla", "barra", "Lácteos y huevos", "mantequilla|margarina|untar", [("125", "125 g", 4900)]),
    ("MKUM", "Kumis", "unidad", "Lácteos y huevos", "kumis|lacteo|fermentado", [("VAS", "vaso de 200 g", 2500), ("1L", "bolsa de 1 litro", 7900)]),
    ("MYOG", "Yogur", "unidad", "Lácteos y huevos", "yogur|yogurt|lacteo", [
        ("FRE", "fresa vaso de 150 g", 2600), ("MEL", "melocotón vaso de 150 g", 2600), ("1LF", "fresa botella de 1 litro", 9900)]),
    # Panadería
    ("MPTA", "Pan tajado", "paquete", "Panadería", "pan|tajado|molde|tostadas", [
        ("BLA", "blanco 500 g", 6900), ("INT", "integral 500 g", 7900)]),
    ("MPAL", "Pan aliñado", "unidad", "Panadería", "pan|alinado|mantequilla", [("UNI", "por unidad", 600)]),
    ("MARE", "Arepa de maíz", "paquete", "Panadería", "arepa|arepas|maiz|blanca", [("5", "paquete de 5", 3900)]),
    ("MGAS", "Galletas de soda", "paquete", "Panadería", "galletas|soda|saladas|tajadas", [("6", "6 tacos", 4900)]),
    # Frutas y verduras
    ("MPAP", "Papa pastusa", "libra", "Frutas y verduras", "papa|pastusa|tuberculo", [("LB", "suelta", 1200)]),
    ("MPCR", "Papa criolla", "libra", "Frutas y verduras", "papa|criolla|amarilla", [("LB", "suelta", 2200)]),
    ("MCEB", "Cebolla cabezona", "libra", "Frutas y verduras", "cebolla|cabezona|blanca|roja", [
        ("BLA", "blanca", 1800), ("ROJ", "roja", 2400)]),
    ("MCEL", "Cebolla larga", "atado", "Frutas y verduras", "cebolla|larga|junca|rama", [("ATA", "atado", 1500)]),
    ("MTOM", "Tomate chonto", "libra", "Frutas y verduras", "tomate|chonto|guiso", [("LB", "suelto", 2400)]),
    ("MPLV", "Plátano verde", "unidad", "Frutas y verduras", "platano|verde|patacon", [("UNI", "por unidad", 1200)]),
    ("MPLM", "Plátano maduro", "unidad", "Frutas y verduras", "platano|maduro|tajadas", [("UNI", "por unidad", 1300)]),
    ("MBAN", "Banano", "unidad", "Frutas y verduras", "banano|guineo|fruta", [("UNI", "por unidad", 500)]),
    ("MLIM", "Limón tahití", "unidad", "Frutas y verduras", "limon|limones|tahiti|fruta", [("UNI", "por unidad", 300)]),
    ("MYUC", "Yuca", "libra", "Frutas y verduras", "yuca|tuberculo", [("LB", "suelta", 1500)]),
    ("MZAN", "Zanahoria", "libra", "Frutas y verduras", "zanahoria|verdura", [("LB", "suelta", 1400)]),
    ("MAGU", "Aguacate", "unidad", "Frutas y verduras", "aguacate|fruta", [("UNI", "por unidad", 3500)]),
    ("MCIL", "Cilantro", "atado", "Frutas y verduras", "cilantro|hierba|aliño", [("ATA", "atado", 1000)]),
    # Bebidas
    ("MGSC", "Gaseosa sabor cola", "botella", "Bebidas", "gaseosa|cola|refresco|soda", [
        ("400", "400 ml", 2800), ("15L", "1,5 litros", 5900), ("3L", "3 litros", 8900)]),
    ("MGSN", "Gaseosa sabor naranja", "botella", "Bebidas", "gaseosa|naranja|refresco|soda", [
        ("400", "400 ml", 2600), ("15L", "1,5 litros", 5400)]),
    ("MAGB", "Agua en bolsa", "bolsa", "Bebidas", "agua|bolsa|potable", [("600", "600 ml", 900)]),
    ("MAGT", "Agua en botella", "botella", "Bebidas", "agua|botella|potable|mineral", [("600", "600 ml", 1800), ("15L", "1,5 litros", 3200)]),
    ("MJUG", "Jugo en caja", "caja", "Bebidas", "jugo|caja|lonchera|fruta", [
        ("MAN", "mango 200 ml", 1700), ("NAR", "naranja 200 ml", 1700)]),
    # Carnes frías
    ("MSAC", "Salchicha", "paquete", "Carnes frías", "salchicha|salchichas|perro", [("10", "paquete de 10", 8900)]),
    ("MJAM", "Jamón de cerdo", "paquete", "Carnes frías", "jamon|cerdo|tajado|sanduche", [("250", "250 g", 7900)]),
    ("MMOR", "Mortadela", "paquete", "Carnes frías", "mortadela|tajada|sanduche", [("250", "250 g", 4900)]),
    # Aseo del hogar
    ("MJBR", "Jabón en barra para ropa", "barra", "Aseo del hogar", "jabon|barra|ropa|lavar", [("300", "300 g", 3200)]),
    ("MDET", "Detergente en polvo", "bolsa", "Aseo del hogar", "detergente|polvo|ropa|lavar", [
        ("500", "500 g", 6900), ("1KG", "1 kg", 12900)]),
    ("MBLQ", "Blanqueador", "botella", "Aseo del hogar", "blanqueador|cloro|limpiar|desinfectar", [
        ("1L", "1 litro", 3900), ("2L", "2 litros", 6900)]),
    ("MLVL", "Lavaloza", "unidad", "Aseo del hogar", "lavaloza|platos|loza", [
        ("CRE", "en crema 450 g", 5900), ("LIQ", "líquido 500 ml", 7400)]),
    ("MESP", "Esponja de cocina", "unidad", "Aseo del hogar", "esponja|platos|cocina|brillo", [("DOB", "doble uso", 1200)]),
    ("MPHI", "Papel higiénico", "paquete", "Aseo del hogar", "papel|higienico|rollos|baño", [
        ("4", "paquete de 4 rollos", 6900), ("12", "paquete de 12 rollos", 18900)]),
    ("MBOL", "Bolsas para basura", "paquete", "Aseo del hogar", "bolsas|basura|negras", [("10", "paquete de 10", 3900)]),
    ("MSUA", "Suavizante para ropa", "botella", "Aseo del hogar", "suavizante|ropa|lavar", [("1L", "1 litro", 8900)]),
    # Aseo personal
    ("MJTO", "Jabón de tocador", "barra", "Aseo personal", "jabon|tocador|baño|ducha", [("110", "110 g", 2900)]),
    ("MCRD", "Crema dental", "unidad", "Aseo personal", "crema|dental|dientes|pasta", [("75", "tubo de 75 ml", 5900)]),
    ("MCHA", "Champú", "unidad", "Aseo personal", "champu|shampoo|cabello", [("SOB", "sobre de 20 ml", 900), ("400", "frasco de 400 ml", 16900)]),
    ("MTOA", "Toallas higiénicas", "paquete", "Aseo personal", "toallas|higienicas|femeninas", [("10", "paquete de 10", 5900)]),
    ("MPNL", "Pañales desechables", "paquete", "Aseo personal", "panales|bebe|desechables", [
        (f"T{size}", f"talla {size}, 30 unidades", price) for size, price in ((1, 32900), (2, 34900), (3, 38900), (4, 42900))]),
    # Mecato
    ("MPFR", "Papas fritas", "paquete", "Mecato", "papas|fritas|paquete|mecato|pasabocas", [
        ("NAT", "naturales 45 g", 2500), ("LIM", "limón 45 g", 2500)]),
    ("MCHT", "Chocolatina", "unidad", "Mecato", "chocolatina|chocolate|dulce|mecato", [("30", "30 g", 1800)]),
    ("MMNI", "Maní salado", "paquete", "Mecato", "mani|salado|pasabocas|mecato", [("50", "50 g", 2200)]),
    ("MCHU", "Chupeta", "unidad", "Mecato", "chupeta|bombon|dulce|mecato", [("UNI", "por unidad", 500)]),
    # Varios del hogar
    ("MVEL", "Velas", "paquete", "Varios del hogar", "velas|vela|luz", [("6", "paquete de 6", 3900)]),
    ("MFOS", "Fósforos", "caja", "Varios del hogar", "fosforos|cerillas|cerillos", [("50", "caja de 50", 500)]),
    ("MPIL", "Pilas AA", "paquete", "Varios del hogar", "pilas|baterias|aa|doble a", [("2", "par", 4900)]),
    ("MALP", "Alimento para perro adulto", "bolsa", "Varios del hogar", "alimento|perro|concentrado|mascota", [
        ("1KG", "1 kg", 9900), ("4KG", "4 kg", 35900)]),
]

# Información de la tienda de mercado que lee consultar_info_tienda. Todo es ficticio.
MARKET_STORE_INFO = {
    "nombre": {"texto": "Tienda La Despensa del Barrio (tienda de demostración)"},
    "horario": {
        "zona_horaria": "America/Bogota",
        "dias": {
            "lunes": ["06:00", "21:00"], "martes": ["06:00", "21:00"], "miercoles": ["06:00", "21:00"],
            "jueves": ["06:00", "21:00"], "viernes": ["06:00", "21:00"], "sabado": ["06:00", "21:00"],
            "domingo": ["07:00", "13:00"],
        },
        "festivos": "Los festivos abre de 7:00 a 13:00.",
    },
    "ubicacion": {"texto": "Carrera 7 # 12-40, barrio San José (dirección ficticia de demostración)."},
    "medios_pago": {"texto": "En el mostrador se recibe efectivo y transferencia desde el celular; no se reciben "
                             "tarjetas. Este asistente no cobra ni recibe pagos."},
    "domicilios": {"texto": "Domicilio gratis en el barrio para compras desde $20.000 COP, coordinado por el "
                            "mostrador. Este asistente no programa entregas."},
    "garantias": {"texto": "Si un producto sale vencido o en mal estado, se cambia el mismo día con el tiquete de "
                           "compra. Frutas, verduras y queso se revisan al momento de recibirlos."},
    "contacto": {"texto": "Reclamos, domicilios y encargos los atiende la persona del mostrador en el horario de la "
                          "tienda."},
    "pedidos": {"texto": "Por este chat se registran pedidos para recoger en la tienda. El pedido se aparta 5 minutos "
                         "mientras lo confirmas; ya confirmado, se guarda hasta 2 horas después de la hora de recogida "
                         "acordada (o 24 horas si no acuerdas hora). El pago se hace en el mostrador al recoger: este "
                         "chat no cobra, no recibe pagos ni fía."},
    "facturacion": {"texto": "Por este chat no se emite factura. El tiquete o la factura electrónica se piden en el "
                             "mostrador al pagar."},
}

# Surtido que anotó el tendero de la tienda de mercado (día del proveedor, fecha o «descontinuado»).
MARKET_RESTOCKS = {
    "MLEC-1L": "lunes", "MHUE-UNI": "martes", "MCUB-30": "martes", "MPTA-BLA": "lunes",
    "MQUE-1LB": "jueves", "MLPO-400": "2026-11-04", "MFEC-380": "descontinuado",
}
