# Pagos de pedidos por chat: alternativas para verificar el cobro

Investigación para AsisTendero, consultada el 26-10-2026. Hoy el pago es siempre en el mostrador y el chat nunca
cobra; este documento no cambia esa regla, solo describe qué haría falta para cambiarla. No se escribió código ni se
hizo ninguna llamada a una API de pagos.

**Cómo leer las marcas de verificación**

- **[LEÍDO]**: la afirmación sale de la página oficial, leída completa o en la sección citada.
- **[EXTRACTO]**: la página oficial bloqueó la lectura automática (protección anti-bots o contenido cargado con
  JavaScript) y el dato sale del extracto que el buscador muestra de esa misma URL oficial. Antes de usarlo en una
  entrega, se abre la página a mano.
- **[NO VERIFICADO]**: no se encontró fuente oficial. No se afirma.

## Lo implementado en el prototipo (26-10-2026)

Sin credenciales ni proveedores: el registro manual del cobro que ya puede hacer el tendero desde su panel.

- **Dónde:** `payments.py` (reglas y tablas `payments` y `payment_events` en la base de la tienda),
  `sales_history.py` (historial y resumen) y la sección **Ventas y pagos** del panel (`ui/tendero-sales.js` y la hoja
  de pago de `ui/tendero-payments.js`).
- **Métodos:** efectivo, datáfono, Nequi, Daviplata, transferencia bancaria y Bre-B.
- **Estados:** `pendiente` → `comprobante_recibido` → `confirmado` o `rechazado`. Efectivo y datáfono solo pasan de
  `pendiente` a `confirmado` y se confirman «en el mostrador»; un pago digital solo se confirma con la revisión del
  tendero en su app o extracto (`revision_tendero`), nunca con un comprobante del cliente.
- **Quién confirma:** solo el tendero. El chat y Grok no registran ni confirman pagos; el agente, a lo sumo, podría
  anotar un comprobante recibido (no está conectado a ninguna herramienta).
- **Monto:** siempre el total del pedido leído de la base; la ruta no acepta un monto.
- **Vendido no es cobrado:** un pedido entregado cuenta como venta; solo un pago confirmado cuenta como ingreso. El
  panel muestra aparte lo «por verificar» (comprobantes) y lo «por cobrar» (ventas sin pago confirmado).
- **Un pago confirmado es final** en el prototipo: devolver o corregir un cobro queda fuera de alcance.
- **Pasarela:** la fuente `pasarela` existe pero se rechaza con `PAYMENT_SOURCE_UNAVAILABLE` hasta integrar un
  proveedor con webhook firmado.

### Qué falta para cobrar y verificar de verdad

1. Elegir la pasarela (por la investigación de abajo, Wompi tiene el sandbox más completo) y abrir la cuenta de
   comercio con los requisitos del titular.
2. Guardar las llaves y el secreto de eventos fuera del repositorio (`.env`, documentado con valores vacíos en
   `.env.example`) y nunca en trazas ni evidencia.
3. Exponer un endpoint HTTPS público solo para el webhook, separado del panel (que sigue escuchando en
   `127.0.0.1`), que verifique la firma, sea idempotente por id de transacción y consulte la transacción con la llave
   privada antes de marcar el pago `confirmado` con la fuente `pasarela`.
4. Que el plan del corte lo pida: hoy pagos y Wompi están fuera de alcance según `AGENTS.md`.

Lo que sigue es la investigación tal como se hizo, con sus marcas de verificación.

## Resumen ejecutivo

1. **Lo único verificable de forma automática es un cobro creado por una pasarela o por la API de Nequi.** Wompi,
   Bold, ePayco, PayU y Mercado Pago confirman el pago con una notificación al servidor del comercio (webhook) firmada
   con un secreto, y tienen consulta de la transacción por API. La redirección del navegador o la «página de respuesta»
   no sirve como prueba: Wompi y ePayco lo dicen de forma explícita.
2. **Una transferencia de persona a persona (al Nequi personal, a una llave Bre-B o a una cuenta) no se puede verificar
   desde el software.** No hay API pública para leer los movimientos de una cuenta personal ni para que un tercero
   consulte si llegó una transferencia Bre-B. Las finanzas abiertas obligatorias en Colombia siguen en
   reglamentación.
3. **Un pantallazo o comprobante no prueba nada por sí solo.** Nequi pide no confiar en pantallazos, usar su QR
   verificador (válido 5 minutos) y confirmar que la plata entró a la cuenta. El control real es que el tendero vea el
   abono en su propia app.
4. **Para el prototipo, lo implementable ya y sin credenciales** es registrar el método de pago que el cliente dice que
   usará y un estado manual: `pendiente_de_pago` → `comprobante_recibido` → `confirmado_por_el_tendero` (o
   `rechazado`). La confirmación solo la da el tendero desde su panel, nunca el chat ni Grok.
5. **La integración automática** requiere cuenta de comercio en una pasarela (RUT y cuenta bancaria en Wompi para
   persona natural), llaves de sandbox, un endpoint HTTPS público para el webhook y almacenar el secreto fuera del
   repositorio. Choca con dos reglas vigentes del repositorio: el visor y el panel escuchan solo en `127.0.0.1`, y
   Wompi y los pagos están fuera de alcance mientras no lo pida el plan del corte (`AGENTS.md`).

## Opción A: pasarela de pagos (link de pago, checkout o API)

El patrón común: el servidor crea el cobro con una referencia propia (el id del pedido), el cliente paga en la página
de la pasarela, la pasarela avisa al servidor con un evento firmado y el servidor, además, puede consultar la
transacción con su llave privada. El pedido solo pasa a «pagado» con el evento verificado o con la consulta, nunca con
lo que diga el cliente.

### Wompi (Bancolombia)

| Tema | Detalle | Fuente |
|---|---|---|
| Crear el cobro | Link de pago: `POST /v1/payment_links` con la llave privada en `Authorization: Bearer`. Campos mínimos `name`, `description`, `single_use`, `collect_shipping`; opcionales `amount_in_cents`, `currency` (solo COP), `expires_at`, `redirect_url`, `sku` (hasta 36 caracteres). `single_use: true` deja de aceptar pagos tras el primero aprobado. El link queda en `https://checkout.wompi.co/l/<id>`. | [LEÍDO] [W1] |
| Firma del checkout | Widget y Web Checkout exigen `signature:integrity` = SHA-256 de `<Referencia><Monto en centavos><Moneda>[<FechaExpiracion>]<SecretoIntegridad>`, calculada en el servidor. | [LEÍDO] [W2] |
| Confirmación | Evento `transaction.updated` por `POST` a la URL configurada (una por ambiente). Checksum SHA-256 de los valores listados en `signature.properties` + `timestamp` + secreto de eventos; también llega en el encabezado `X-Event-Checksum`. Las propiedades no son un arreglo fijo: se leen de cada evento. Si no coincide, se ignora. Se responde HTTP 200; si no, reintenta 3 veces en 24 horas (≈30 min, 3 h, 24 h). | [LEÍDO] [W3] |
| Consulta | `GET /v1/transactions/{id}` solo con llave privada desde el servidor; sin llave o con la pública devuelve 404. Estados: `PENDING`, `APPROVED`, `DECLINED`, `VOIDED` (solo tarjeta), `ERROR`. No se documenta consulta por `reference`. | [LEÍDO] [W4] |
| Advertencias | «No utilices la redirección como método de validación de tus transacciones»; la consulta desde el frontend ya no está soportada. | [LEÍDO] [W2] |
| Métodos | `CARD`, `BANCOLOMBIA_TRANSFER`, `NEQUI`, `PSE`, `BANCOLOMBIA_COLLECT` (efectivo en corresponsal), `PCOL`, `BANCOLOMBIA_BNPL`, `DAVIPLATA`, `SU_PLUS`, `BANCOLOMBIA_QR`. Bre-B solo aparece como «Dispersiones con BRE-B», es decir, para enviar dinero, no para cobrar. | [LEÍDO] [W5], [W6] |
| Ambientes y llaves | Sandbox `https://sandbox.wompi.co/v1`, producción `https://production.wompi.co/v1`. Prefijos: `pub_test_`/`prv_test_`/`test_events_`/`test_integrity_` y sus equivalentes `_prod_`. Ambientes independientes. | [LEÍDO] [W7] |
| Datos de prueba | Tarjeta `4242 4242 4242 4242` aprueba y `4111 1111 1111 1111` rechaza; Nequi `3991111111` aprueba y `3992222222` rechaza; PSE con `financial_institution_code` `"1"`/`"2"`; Bancolombia QR con `sandbox_status`. | [LEÍDO] [W8] |
| Requisitos | Persona natural: documento de identidad, RUT sin contraseña, cuenta Bancolombia con más de 30 días o cuenta Nequi; el primer desembolso llega 30 días después de la primera transacción. Persona jurídica: documento del representante legal y RUT; la página no detalla más. | [LEÍDO] [W9] |
| Costos | Plan Avanzado (agregador): 2,65 % + $700 + IVA por transacción exitosa; código QR 1 % por transacción exitosa, «solo para personas naturales». Plan Gateway sin comisión de Wompi, para comercios con más de 2.000 transacciones. | [LEÍDO] [W10] |

### Bold

| Tema | Detalle | Fuente |
|---|---|---|
| Productos | API Link de pagos, Botón de pagos, API de pagos en línea, Webhooks, API Integrations (datáfono), Applink. | [LEÍDO] [B1] |
| Crear el cobro | `POST https://integrations.api.bold.co/online/link/v1` con `Authorization: x-api-key <llave>` (la del Botón de pagos). `amount_type` `OPEN` o `CLOSE`; `reference` hasta 60 caracteres; `expiration_date`; `callback_url` HTTPS; `payment_methods` como `CREDIT_CARD`, `PSE`, `BOTON_BANCOLOMBIA`, `NEQUI`. Devuelve `payload.url`. La unidad de `expiration_date` es ambigua en la página (dice nanosegundos, los ejemplos tienen 13 dígitos). | [LEÍDO] [B2] |
| Estado del link | `GET /online/link/v1/{payment_link}`: `ACTIVE`, `PROCESSING`, `PAID`, `REJECTED`, `CANCELLED`, `EXPIRED`, con `transaction_id` e `is_sandbox`. | [LEÍDO] [B2] |
| Confirmación | Eventos `SALE_APPROVED`, `SALE_REJECTED`, `VOID_APPROVED`, `VOID_REJECTED`. Encabezado `x-bold-signature` = HMAC-SHA256 en hexadecimal del cuerpo codificado en Base64, con la llave secreta del producto. Responder 200 en menos de 2 s; hasta 5 reintentos (15 min, 1 h, 4 h, 8 h, 24 h); puede duplicar, así que se exige idempotencia por id de pago. | [LEÍDO] [B3] |
| Consulta de respaldo | `GET https://integrations.api.bold.co/payments/webhook/notifications/<payment_id>` (o por referencia externa con `is_external_reference=true`). Bold pide no usarla como fuente principal. | [LEÍDO] [B3] |
| Pruebas | En modo prueba la llave secreta es cadena vacía y las notificaciones no se envían, salvo con «Probar el webhook». | [LEÍDO] [B3] |
| Costos | Venta con link de pago: 2,99 % + $900 + retenciones de ley. | [EXTRACTO] [B4] |
| Requisitos | Persona natural con cédula y cuenta bancaria; el manual del link dice que hace falta un datáfono Bold asociado. Las fuentes se contradicen. | [EXTRACTO] [B5], [B6]; contradicción sin resolver |

### ePayco (Davivienda)

| Tema | Detalle | Fuente |
|---|---|---|
| Confirmación | URL de confirmación (servidor a servidor). Firma `x_signature` = SHA-256 de `p_cust_id_cliente^p_key^x_ref_payco^x_transaction_id^x_amount^x_currency_code`. Estado en `x_response`: Aceptada, Rechazada, Pendiente, Fallida. | [LEÍDO] [E1] |
| Consulta | `GET https://secure.epayco.co/validation/v1/reference/{ref_payco}`. | [LEÍDO] [E1] |
| Advertencia | La página de respuesta no es confiable para el estado final; se confirma en el backend. Verificar que el valor pagado coincida con el pedido y evitar procesar dos veces. | [EXTRACTO] [E2] |
| Métodos | Más de 22; lista Daviplata y PSE. Nequi no aparece en la página de tarifas. Menciona «Acepta pagos presenciales con Bre-B» sin detalle. | [LEÍDO] [E3] |
| Costos | Agregador: 2,64 % + $690 + IVA con cuenta Davivienda; 3,29 % + $700 + IVA con otros bancos. PSE menor a $60.000: $2.000 + IVA. | [LEÍDO] [E3] |
| Pruebas | Solo consta el campo `x_test_request`; cómo activar el modo prueba no está en la página leída. | [LEÍDO] [E1] |
| Requisitos | Persona natural: cédula o pasaporte, RUT y certificación bancaria (términos del modelo agregador). | [EXTRACTO] [E4] |

### PayU Colombia

| Tema | Detalle | Fuente |
|---|---|---|
| Métodos (API) | Tarjeta, **QR Bre-B** (`INTEROPERABLE_QR`), PSE, Google Pay, Nequi, Botón Bancolombia, efectivo y referencia bancaria. | [LEÍDO] [P1] |
| QR Bre-B | QR dinámico de monto fijo que el pagador escanea con la app de su banco o billetera; vence a los 15 minutos; la respuesta inicial queda `PENDING` con `AWAITING_NOTIFICATION` y el pago llega a la cuenta virtual PayU. | [LEÍDO] [P1] |
| Confirmación | `notifyUrl` de la transacción o URL de confirmación del módulo; o la API de consultas. Firma `sign` = MD5 de `apiKey~merchant_id~reference_sale~new_value~currency~state_pol` con los valores recibidos, no los de la base propia; `state_pol` 4 = aprobada, 6 = declinada. La página menciona también un método HMAC-SHA256: se confirma en el panel cuál está activo. | [EXTRACTO] [P2] |
| Ambientes | Sandbox `https://sandbox.api.payulatam.com/payments-api/4.0/service.cgi`; producción `https://api.payulatam.com/payments-api/4.0/service.cgi`; `test: true`. | [LEÍDO] [P1] |
| Costos | 3,29 % + $300 (página de precios en inglés); una página antigua dice 2,79 % + $800. | [EXTRACTO] [P3] |
| Requisitos | [NO VERIFICADO] | — |

### Mercado Pago Colombia

| Tema | Detalle | Fuente |
|---|---|---|
| Métodos (Checkout Pro) | Tarjeta crédito o débito, cuenta Mercado Pago, PSE y Efecty. Nequi aparece solo como banco dentro de PSE, no como método propio. | [EXTRACTO] [M1] |
| Confirmación | Webhook con encabezado `x-signature` (`ts=…,v1=…`) verificado por HMAC con el secreto de la aplicación; los SDK reciben `x-signature`, `x-request-id` y `data.id`. Responder 200/201 en 22 s; reintenta cada 15 min. El recurso completo se consulta con `GET https://api.mercadopago.com/v1/payments/{id}`. La plantilla exacta del texto firmado no está en la página leída. | [LEÍDO] [M2] |
| Costos y requisitos | [NO VERIFICADO] | — |

## Opción B: QR de Nequi

### API oficial de Nequi para comercios (Nequi Conecta / Portal de Desarrolladores)

- **Existe.** Nequi publica APIs de recaudo: pagos con QR dinámico, pagos con notificación push y suscripciones;
  además dispersiones, códigos por plata, reportería y token de seguridad. El alta se hace en el portal B2B y el Portal
  de Desarrolladores; leer la documentación y usar el sandbox es gratis y el costo depende del producto, sin precios
  publicados. [LEÍDO] [N1]
- **QR dinámico por API:** el comercio lo genera indicando monto, es de una sola transacción y la confirmación se
  obtiene **consultando el estado** («endpoint tipo getStatus»); la página no menciona webhooks. «Disponible solo para
  comercios con contrato vigente, certificación y pruebas previas.» [LEÍDO] [N2]
- **Endpoints productivos** (`https://api.nequi.com/payments/v2/...`): push = *Unregistered Payment*, *Get Status
  Payment*, *Reverse Transaction*, *Cancel unregistered payment*; QR = *Generate Code QR*, *Get Status Payment*,
  *Reverse Transaction*, *Cancel QR payment*. Token OAuth2 en `https://oauth.nequi.com/oauth2/token`. [LEÍDO] [N3]
- **Proceso:** llaves de prueba por Slack en un día hábil; certificación enviando casos de prueba en JSON y video a
  `certificacion@conecta.nequi.com`; aprobación hasta 4 días hábiles. Casos obligatorios del QR: pago exitoso con
  consulta de estado, QR vencido a los 45 minutos y reverso. [LEÍDO] [N3]
- **Requisitos de tipo de persona o NIT para la API:** las páginas leídas no los dicen. [NO VERIFICADO]
- **Nequi Negocios** (vinculación): persona natural con cédula, RUT «si tienes» y cuenta Nequi o certificación
  Bancolombia; persona jurídica con cámara de comercio, cédula del representante, composición accionaria y
  certificación Bancolombia. La app permite cobrar con QR, tarjetas y link de pago, y el «QR Negocios» recibe pagos de
  otros bancos. [LEÍDO] [N4]

### QR personal o de Negocios frente a QR dinámico por API

| | QR estático (personal o Nequi Negocios) | QR dinámico por API de Nequi |
|---|---|---|
| Quién lo genera | La app, una vez; se imprime | El servidor del comercio, uno por cobro |
| Monto | Lo digita el cliente | Fijo, lo pone el comercio |
| Asociación con el pedido | Ninguna: no lleva referencia del pedido | Una transacción por QR |
| Cómo se sabe que pagó | El tendero mira su app o su cuenta | `Get Status Payment` desde el servidor |
| Requisito | Cuenta Nequi o Nequi Negocios | Contrato, certificación y llaves de producción |

Fuentes: [N2], [N3], [N4]. Que el QR estático no lleve referencia del pedido es una inferencia de que el monto lo
digita el pagador ([BR1]); no se encontró documentación de Nequi que lo diga.

### ¿Se puede verificar por software una transferencia P2P al Nequi personal del tendero?

**No con fuentes oficiales.** Ninguna página de Nequi consultada ofrece una API para leer los movimientos de una
cuenta personal o confirmar que llegó una transferencia de otra persona; la API de reportería es para comercios
integrados ([N1]). Lo que Nequi sí ofrece es verificación **manual** (sección Comprobantes). Raspar la app, leer las
notificaciones del celular del tendero o pedirle su clave no tiene respaldo oficial y no se recomienda.

## Opción C: verificación de transferencias y Bre-B

### Estado de Bre-B

- Sistema de pagos inmediatos interoperable del Banco de la República; se usa desde las apps de las entidades
  financieras, no es una app aparte. [LEÍDO] [BR1]
- Operación plena desde el 6 de octubre de 2025. [EXTRACTO] [BR2]
- Una transferencia inmediata no puede tardar más de 20 segundos; tope por operación de 1.000 UVB, $12.110.000 en 2026,
  y cada entidad puede fijar límites propios. [LEÍDO] [BR1] para el tope; [EXTRACTO] [BR3] para los 20 segundos.
- Cinco tipos de llave: documento, celular, correo, alfanumérica con `@` y **código de establecimiento de comercio**
  (solo comercios). Registrar llaves no cuesta; las tarifas de las transferencias las fija cada entidad. [LEÍDO] [BR1]
- QR estáticos (el usuario digita el monto) y dinámicos (uno por operación). Los comercios pueden usar QR desde el
  inicio; para personas naturales generar su propio QR se anunció para 2026 con fechas que no coinciden entre
  publicaciones del Banco (primer semestre en enero; segundo semestre en abril). No se encontró confirmación de que
  ya esté disponible. [EXTRACTO] [BR2], [BR4]
- Al primer año (6-10-2026): más de 36 millones de usuarios, más de 1.700 millones de transacciones y más de 116
  millones de llaves. [EXTRACTO] [BR5]
- Los reclamos se radican ante la entidad financiera de la cuenta, no ante el Banco de la República. [EXTRACTO] [BR1]
- Si la operación es irrevocable o cómo se devuelve: una presentación del Banco menciona procesos de devolución y
  reversión sin detallarlos. [NO VERIFICADO] como regla para el usuario.

### ¿Puede un comercio pequeño recibir pagos Bre-B?

Sí: una persona natural puede recibir con sus llaves personales, y un comercio con la llave de código de
establecimiento o el QR que le dé su entidad ([BR1]). Bancolombia ya deja a los negocios con QR registrar otras llaves
(Bancolombia Negocios, correo, NIT o cédula para independientes, celular) y advierte que, al cambiar la llave, el QR
físico debe reemplazarse ([BC1], 7-5-2026).

### ¿Hay un mecanismo para que un tercero verifique la recepción?

- **Directamente sobre Bre-B: no.** Las preguntas frecuentes no mencionan una API para terceros; las entidades deben
  informar a **sus clientes** el estado de las transacciones ([BR1]). Conectarse a Bre-B es para entidades
  participantes, no para un software de tienda.
- **A través de una pasarela: sí, en un caso comprobado.** PayU genera un QR Bre-B dinámico (`INTEROPERABLE_QR`) y
  notifica el resultado como cualquier otra transacción ([P1]). Es la única vía documentada encontrada para cobrar por
  Bre-B y verificar el pago por software. Wompi documenta Bre-B solo para dispersiones ([W6]); ePayco menciona Bre-B
  presencial sin documentación técnica ([E3]).
- **Finanzas abiertas:** la Circular Externa 004 de 2024 de la Superfinanciera fijó estándares de APIs y el Decreto
  368 de 2026 creó el modelo obligatorio, con cronograma de estándares aún en ajuste. No hay hoy un estándar
  publicado que permita a un tercero consultar movimientos de una cuenta de depósito. [EXTRACTO] [SF1], [SF2]

## Comprobantes y capturas de pantalla

**Riesgo.** Un pantallazo se edita en segundos y no prueba que el dinero llegó. Nequi pide explícitamente no confiar
en pantallazos ([N5]). Bancolombia documenta, además, el fraude de reemplazar el QR impreso del comercio por el de un
tercero ([BC2]).

**Lo que recomiendan las fuentes oficiales**

1. Escanear el **QR verificador** del comprobante con la app Nequi: «Usa tu QR» → «Comprueba un pago». El cliente lo
   genera desde «Movimientos» y vale 5 minutos. [LEÍDO] [N5]
2. Revisar que fecha y hora coincidan con el momento del pago y que el comprobante muestre el nombre del negocio.
   [LEÍDO] [N5]
3. Un comprobante con marca «ANULADO» y sin QR verificador no corresponde a un pago exitoso. [LEÍDO] [N5]
4. Confirmar en la cuenta propia que la plata entró. [LEÍDO] [N5]
5. Revisar con frecuencia que el QR impreso no esté alterado y hacer una transferencia de prueba. [EXTRACTO] [BC2]

**Flujo manual razonable para AsisTendero** (propuesta, no fuente):

1. El cliente dice en el chat cómo va a pagar. El chat responde con los datos de pago que el tendero configuró y
   aclara que el pedido queda **pendiente hasta que el tendero confirme el abono**.
2. Si el cliente manda un comprobante, el pedido pasa a `comprobante_recibido`. El chat no lo interpreta ni dice
   «pago recibido».
3. El tendero abre su app (o escanea el QR verificador si es Nequi), comprueba monto, hora y remitente, y marca
   `confirmado_por_el_tendero` o `rechazado` en el panel. Queda en el historial quién confirmó y cuándo.
4. Si nadie confirma, el pedido sigue su vencimiento normal y el pago se cobra en el mostrador.

## Tabla comparativa

| Opción | Verifica el pago por software | Métodos | Requisitos | Costo publicado | Sandbox | Encaja en el prototipo hoy |
|---|---|---|---|---|---|---|
| Wompi (link o checkout) | Sí: evento firmado SHA-256 + consulta con llave privada | Tarjeta, PSE, Nequi, Daviplata, Botón y QR Bancolombia, efectivo | Persona natural con RUT y cuenta Bancolombia (>30 días) o Nequi | 2,65 % + $700 + IVA; QR 1 % | Sí, con datos de prueba | No: fuera de alcance y necesita URL HTTPS pública |
| Bold (link de pagos) | Sí: HMAC-SHA256 + consulta de respaldo | Tarjeta, PSE, Botón Bancolombia, Nequi | Cédula y cuenta; posible datáfono (contradictorio) | 2,99 % + $900 [EXTRACTO] | Parcial (webhook de prueba manual) | No, por las mismas razones |
| ePayco | Sí: SHA-256 en confirmación + consulta por referencia | Tarjeta, PSE, Daviplata, otros | Cédula, RUT, certificación bancaria [EXTRACTO] | 2,64–3,29 % + $690–700 + IVA | Campo de prueba; activación no verificada | No |
| PayU | Sí: firma MD5 (o HMAC) + API de consultas | Tarjeta, PSE, Nequi, Botón Bancolombia, **QR Bre-B** | [NO VERIFICADO] | 3,29 % + $300 [EXTRACTO] | Sí | No |
| Mercado Pago | Sí: HMAC `x-signature` + `GET /v1/payments/{id}` | Tarjeta, PSE, Efecty, cuenta MP | [NO VERIFICADO] | [NO VERIFICADO] | No verificado | No |
| API Nequi (QR dinámico o push) | Sí: consulta de estado, sin webhook documentado | Solo Nequi | Contrato, certificación, pruebas QA | Sin precio publicado | Sí | No: proceso comercial y certificación |
| QR estático Nequi o llave Bre-B del tendero | **No** | Nequi; Bre-B desde cualquier entidad | Cuenta propia | Registro de llaves gratis; transferencias según entidad | — | Sí, solo con confirmación manual |
| Comprobante o pantallazo | **No** (solo el QR verificador de Nequi, y a mano) | Cualquiera | Ninguno | — | — | Sí, como señal, nunca como prueba |

## Recomendación

**Se puede implementar ya, sin credenciales ni llamadas externas** (si el plan del corte lo pide):

- Un campo `metodo_pago` en el pedido (`mostrador`, `nequi`, `bre_b`, `transferencia`) que el cliente declara.
- Estados de pago separados del estado del pedido: `pendiente_de_pago`, `comprobante_recibido`,
  `confirmado_por_el_tendero`, `rechazado`. Solo el panel del tendero pasa a `confirmado_por_el_tendero`; ni Grok ni
  el chat pueden hacerlo, y la regla vive en el código como las demás de `order_rules.py`.
- Que el chat diga los datos de pago configurados por el tendero y nunca afirme «pago recibido». Encaja con la regla
  de `AGENTS.md` de no afirmar pago.
- Pruebas que miren lo que no debe pasar: el chat marcando un pago como confirmado, un comprobante cambiando el estado
  a confirmado, un cliente viendo el pago de otro pedido.

**Requiere cuenta y llaves de un proveedor:**

- Link de pago con Wompi o Bold (o QR Bre-B con PayU) con la referencia del pedido, webhook verificado con el secreto
  de eventos y consulta de la transacción antes de marcar «pagado». El sandbox de Wompi es el más completo de los
  revisados para probar sin dinero real ([W7], [W8]).
- Necesita: RUT y cuenta bancaria del tendero, llaves de prueba en `.env` (nunca en el repositorio), un endpoint HTTPS
  accesible desde internet (choca con «solo `127.0.0.1`») e idempotencia por id de transacción. Antes de hacerlo hay
  que cambiar el alcance del corte y anotar la excepción a la regla del visor local.

**Inviable o no verificable:**

- Confirmar automáticamente una transferencia P2P a un Nequi personal, a una llave Bre-B o a una cuenta bancaria.
- Validar un pantallazo por software (OCR o similar): no prueba que el dinero llegó y las fuentes piden revisar la
  cuenta.
- Conectarse directamente a Bre-B o leer movimientos por finanzas abiertas: hoy no hay acceso para un software de
  tienda.

## Afirmaciones sin verificar

- Requisitos para abrir cuenta en PayU y en Mercado Pago Colombia, y las tarifas de Mercado Pago.
- Requisitos de tipo de persona o NIT para usar la API de Nequi.
- Si Wompi o Bold aceptan cobros por Bre-B (solo se encontró Wompi para dispersiones).
- Si una transferencia Bre-B es irrevocable y cómo se devuelve.
- Si las personas naturales ya pueden generar su propio QR Bre-B.
- Tarifas de Bold, requisitos de ePayco, operación plena de Bre-B y los 20 segundos: solo extracto del buscador sobre la
  URL oficial (bloqueo anti-bots o contenido en JavaScript).
- La plantilla exacta del texto firmado del webhook de Mercado Pago y el algoritmo activo en PayU (MD5 o HMAC).

## Fuentes (consultadas el 26-10-2026)

**Wompi**

- [W1] Links de pago: https://docs.wompi.co/docs/colombia/links-de-pago/
- [W2] Widget y Web Checkout (firma de integridad): https://docs.wompi.co/docs/colombia/widget-checkout-web/
- [W3] Eventos: https://docs.wompi.co/docs/colombia/eventos/
- [W4] Seguimiento de transacciones: https://docs.wompi.co/docs/colombia/seguimiento-de-transacciones/
- [W5] Métodos de pago: https://docs.wompi.co/docs/colombia/metodos-de-pago/
- [W6] Guía de dispersiones Bre-B: https://docs.wompi.co/en/docs/colombia/guia-integracion-breb/
- [W7] Ambientes y llaves: https://docs.wompi.co/docs/colombia/ambientes-y-llaves/
- [W8] Datos de prueba en sandbox: https://docs.wompi.co/docs/colombia/datos-de-prueba-en-sandbox/
- [W9] Cómo crear una cuenta: https://wompi.com/es/co/ayuda/como-crear-cuenta
- [W10] Planes y tarifas: https://wompi.com/es/co/planes-tarifas/

**Bold**

- [B1] Portal de desarrolladores: https://developers.bold.co/
- [B2] API Link de pagos: https://developers.bold.co/pagos-en-linea/api-link-de-pagos
- [B3] Webhooks: https://developers.bold.co/webhook
- [B4] Tarifas (extracto): https://bold.co/tarifas.html
- [B5] Link de pago (extracto): https://datafonos.bold.co/link-de-pago/
- [B6] Manual del link de cobro (extracto): https://bold.co/assets/documentos/MANUAL_LINK_DE_COBRO_BOLD_PDF.pdf

**ePayco**

- [E1] Páginas de respuesta y confirmación: https://docs.epayco.com/docs/checkout-respuesta-y-confirmacion
- [E2] URL de confirmación (extracto): https://docs.epayco.com/docs/url-de-confirmacion
- [E3] Tarifas: https://epayco.com/tarifas/
- [E4] Términos del modelo agregador (extracto): https://epayco.com/terminos-y-condiciones-generales-2026/

**PayU**

- [P1] API de Pagos Colombia: https://developers.payulatam.com/latam/es/docs/integrations/api-integration/payments-api-colombia.html
- [P2] URL de confirmación (extracto): https://developers.payulatam.com/latam/es/docs/integrations/confirmation-url.html
- [P3] Precios (extracto): https://colombia.payu.com/en/prices/

**Mercado Pago**

- [M1] Checkout Pro, resumen (extracto): https://www.mercadopago.com.co/developers/es/docs/checkout-pro/overview
- [M2] Webhooks: https://www.mercadopago.com.co/developers/es/docs/your-integrations/notifications/webhooks

**Nequi**

- [N1] APIs para negocios: https://www.nequi.com.co/negocios/apis
- [N2] Pago con QR (API): https://www.nequi.com.co/negocios/api-qr
- [N3] ¿Cómo te integras?: https://www.nequi.com.co/negocios/como-te-integras
- [N4] Vinculación de negocios: https://www.nequi.com.co/negocios/vinculacion
- [N5] Tips de seguridad para tu negocio: https://www.nequi.com.co/negocios/tips-de-seguridad-para-tu-negocio
- [N6] ¿Cómo saber si un pago hecho desde Nequi es real? (bloqueó la lectura; mismo contenido que [N5] según el
  extracto): https://ayuda.nequi.com.co/hc/es/articles/34035891603341

**Banco de la República (Bre-B)**

- [BR1] Preguntas frecuentes de Bre-B: https://www.banrep.gov.co/es/bre-b/preguntas-frecuentes
- [BR2] Conozca Bre-B (extracto, anti-bots): https://www.banrep.gov.co/es/bre-b/que-es
- [BR3] Documento técnico Bre-B, febrero de 2026 (extracto; el PDF no se pudo leer):
  https://www.banrep.gov.co/sites/default/files/publicaciones/archivos/documento-tecnico-bre-b-febrero-2026.pdf
- [BR4] Seis meses de operación (extracto): https://www.banrep.gov.co/en/news/six-months-operation-bre-b-34-million-registered-users
- [BR5] Bre-B cumple un año (extracto, anti-bots): https://www.banrep.gov.co/es/noticias/bre-b-cumple-un-anio-en-colombia

**Bancolombia**

- [BC1] Actualizar el código QR para recibir transferencias Bre-B (7-5-2026):
  https://www.bancolombia.com/acerca-de/sala-prensa/noticias/productos-servicios/actualizar-codigo-qr-para-recibir-transferencias-bre-b
- [BC2] Fraude por transferencia con código QR (extracto):
  https://www.bancolombia.com/acerca-de/sala-prensa/noticias/productos-servicios/fraude-por-transferencia-bancaria-por-codigo-qr

**Superintendencia Financiera y URF (finanzas abiertas)**

- [SF1] URF, sistema de finanzas abiertas obligatorio (extracto):
  https://www.urf.gov.co/w/colombia-consolida-el-sistema-de-finanzas-abiertas-obligatorio
- [SF2] Superfinanciera, mesas técnicas de finanzas abiertas (extracto):
  https://www.superfinanciera.gov.co/publicaciones/10116162/superfinanciera-realizo-las-primeras-mesas-tecnicas-en-el-proceso-de-implementacion-de-las-finanzas-abiertas-obligatorias/
