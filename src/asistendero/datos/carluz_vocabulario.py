"""Cómo se lee la hoja de Carluz: categorías, abreviaturas y sinónimos del mostrador. Solo palabras, ningún dato.

Las claves van en mayúsculas sin tildes (``carluz.plain``). Una palabra sin categoría cae en ``OTHER_CATEGORY``;
la importación reporta cuántas para que se vea, no se adivina.
"""

OTHER_CATEGORY = "Otros artículos"

CATEGORIES = {
    "Tornillería y fijación": frozenset("""
        TORNILLO TORNILLOS TUERCA ARANDELA WASA GUASA CHAZO CANCAMO PUNTILLA CLAVO REMACHES SOPORTE ESCUADRA ABRAZADERA
        SEMIABRAZADERA ARGOLLA GANCHO GRAPA GRAP TENSOR ARMELLAS FISTOS ESTOPEROLES AMARRE CORREAS CHIPOTE BRIDA
        ANOLOC PLATINAS GUAYA CADENA LAZO PITA PIOLA NYLON ZIMBRA PERFIL RIEL CUADRANTE ESQUINERO ESQUINEROS
    """.split()),
    "Plomería y grifería": frozenset("""
        LLAVE TUBO TUBERIA CODO CODOS SEMICODO UNION TAPON BUJE NIPLE NIPLES TEE TE SIFON VALVULA REGISTRO DUCHA
        MANGUERA GRIFERIA EMPAQUE EMPAQUES ACOPLE RACOR CHEQUE MEZCLADOR LAVAMANOS LAVAPLATOS LAVADERO LAVADORA
        SANITARIA SANITARIO ACCESORIO REJILLA BOQUILLA BOQUILLLA CANASTILLA FLAPER FILTRO DESAGUE BAJANTE PEDESTAL
        REGADERA SUBCJ BASTAGO ASIENTO DOMESTICO GASTOP HEMBRA MACHO ROSCADA DESVIADOR CURVA CHUPA PVC TANQUE
        PEGATANQUE ALARGUE CHIFLON CHIPA GOSNES CONCOLOR DILATADOR DILATACIONES ELE JABONERA TOALLERO PORTAROLLO
    """.split()),
    "Eléctricos e iluminación": frozenset("""
        CABLE ALAMBRE TOMA INTERRUPTOR INTERRUPUTOR SWITCH SUICHE BOMBILLO LAMPARA PLAFON CLAVIJA BREAKER SOCKET CAJA
        CONDUIT CONDUFLEX CANALETA CORAZA EXTENSION MULTITOMA TERMINAL ELECTRICA TIMBRE LINTERNA PILAS BATERIA PROBADOR
        CONVERTIDOR SPLITER RJ ANTENAS ADAPTADOR ROSETA PIN PROTECTOR REGULADOR VELA MOTOR
    """.split()),
    "Pinturas y acabados": frozenset("""
        VINILO VINIPLAST VINIPLAS ESMALTE LACA AEROSOL ESTUCO ESTUCA BROCHA RODILLO LIJA TINTILLA ANTICORROSIVO
        PINTULUX PINTURA PINTULACA PINCEL EMULSION MASILLA SELLADOR PRIMER FONDO BLANCO BOXER CASACRYL INVERCRYL
        DURALAC THINER VARSOL REMOVEDOR METALISOL COLOR CERA GOLD CAOLIN CAL YESO GRANYPLAST VINIPEL DUROLEX LANILLA
        BRILLA LIMPIADOR ESPATULA LLANA LLANAS
    """.split()),
    "Herramientas": frozenset("""
        BROCA DISCO DESTORNILLADOR MARTILLO ALICATE PINZA TENAZA TIJERA SERRUCHO SEGUETA MACHETA PALUSTRE NIVEL
        FLEXOMETRO DECAMETRO CINCEL COMBO PORRA PALA PICA AZADON RASTRILLO HACHA CUCHILLA CUCHILLO BISTURI LIMA
        CEPILLO GRATA PISTOLA PISTOLAS TALADRO CALADORA PULIDORAS REMACHADORAS CAUTIN JUEGO KIT HOJA HOJAS PUNTA
        ESCOBILLA ESCOBILLAS CABO CARRETILLA LLANTA NEUMATICO PLOMADAS REGLA CERCHA PALADRAGA PALIN CARETA GAFAS
        GUANTE GUANTES BOTAS MANO LAPIZ IMAN MEZCLAR BENJAMIN COPA SOLDADURA SOLDA SOLDAQURA SOLDALIST ESTANO
    """.split()),
    "Construcción": frozenset("""
        CEMENTO VARILLA TEJA MALLA LADRILLO ARENA LAMINA ANGEO LOSA TABLA TABLON LISTON PIEDRA TRITURADO CUMBRERA
        FACHALETA BLER SACO COSTAL ALAMBRON PLASTICO VIDRIO ROLLO MARCO BASTIDOR CUBIERTA MINI TELA
    """.split()),
    "Cerrajería y herrajes": frozenset("""
        BIS BISAGRA CANDADO CERRADURA CHAPA MANIJA PORTACANDADO PASADOR BANDOLA CIERRE CIERE TOPE APLIQUES PATA
        BRAZO BASE PORTA RODAJA ROD BOTON MARIPOSA MARIPOSAS CORTINA
    """.split()),
    "Adhesivos y selladores": frozenset("""
        SIKA SIKAFILL SIKADUR SIKAFLEX SIKALATEX SIKASET SIKASIL SILICONA PEGANTE COLBON PEGACOR PEGAFLEX SUPERMASTIC
        SINTESOLDA CINTA ATAFACIL ESTOPA GRAFITO ESPUMA
    """.split()),
    "Hogar, jardín y aseo": frozenset("""
        VENENO BOTELLA ENVASE TARRO POMAS RECIPIENTE EMBUDO VALDE CERNIDOR ANZUELOS CREOLINA ACIDO DESOLORIN SODA
        ACEITE GRASA VASELINA RUANA MIMBRE PALOS MARRANITO PLATO BANDEJA
    """.split()),
}

# Llaves que son herramienta: el resto de «LLAVE…» de la hoja es de agua o de gas.
TOOL_KEYS = frozenset({"BOCA", "EXPANSIVA", "AJUSTABLE", "TALADRO", "TUBO", "ALLEN", "HEXAGONAL", "MIXTA", "ESTRELLA"})

# Lo que el cliente lee: arregla errores y abreviaturas de la hoja sin cambiar qué producto es.
DISPLAY_WORDS = {
    "BIS": "bisagra", "ZIN": "zinc", "PAV": "pavonada", "PAQ": "paquete", "PQTE": "paquete",
    "INTERRUPUTOR": "interruptor", "SUICHE": "interruptor", "SOLDAQURA": "soldadura", "BOQUILLLA": "boquilla",
    "DRIWALL": "drywall", "DRAYWALL": "drywall", "THINER": "thinner", "VINIPLAS": "viniplast",
    "VINILPLAST": "viniplast", "CIERE": "cierre", "ELECTRICA": "eléctrica", "ELECTRICO": "eléctrico",
    "PLASTICO": "plástico", "PLASTICA": "plástica", "METALICA": "metálica", "METALICO": "metálico",
    "VALVULA": "válvula", "SIFON": "sifón", "UNION": "unión", "TAPON": "tapón", "GALON": "galón",
}

# Cómo se dice en el mostrador lo que la hoja nombra de otra forma.
ALIASES = {
    "BIS": ("bisagra", "bisagras"), "BISAGRA": ("bisagras",),
    "SWITCH": ("interruptor",), "SUICHE": ("interruptor",), "INTERRUPUTOR": ("interruptor",),
    "VINILO": ("pintura",), "VINIPLAST": ("pintura", "vinilo"), "VINIPLAS": ("pintura", "vinilo"),
    "VINILPLAST": ("pintura", "vinilo"), "ESMALTE": ("pintura",), "PINTULUX": ("pintura", "esmalte"),
    "ANTICORROSIVO": ("pintura",), "LACA": ("pintura",), "AEROSOL": ("pintura", "spray"),
    "BOMBILLO": ("foco", "bombilla"), "LAMPARA": ("foco",), "PLAFON": ("lampara",),
    "BREAKER": ("taco", "interruptor"), "FLEXOMETRO": ("metro", "cinta metrica", "decametro"),
    "DECAMETRO": ("metro", "cinta metrica"), "DRIWALL": ("drywall",), "DRAYWALL": ("drywall",),
    "THINER": ("thinner", "disolvente"), "VARSOL": ("disolvente",), "COLBON": ("pegante", "cola"),
    "SIKA": ("impermeabilizante",), "VENENO": ("insecticida", "matarratas"), "CHAZO": ("taco", "chazos"),
    "PUNTILLA": ("clavo",), "CLAVO": ("puntilla",), "WASA": ("arandela",), "GUASA": ("arandela",),
    "TUBERIA": ("tubo",), "SEMICODO": ("codo",), "CHUPA": ("destapador", "sopapa"), "EXTENSION": ("alargue",),
    "MULTITOMA": ("regleta", "extension"), "MACHETA": ("machete",), "PALUSTRE": ("cuchara",),
    "SEGUETA": ("sierra",), "SERRUCHO": ("sierra",), "ESTUCO": ("masilla",), "CANDADO": ("cerrojo",),
    "CERRADURA": ("chapa",), "CHAPA": ("cerradura",), "ESTANO": ("soldadura",), "SOCKET": ("portalampara",),
}
