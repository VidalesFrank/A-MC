# Modelador de muros de contención — SAP2000

Generador paramétrico de modelos de muros de contención sobre pilas con viga
cabezal. Se introducen las dimensiones, materiales, estratigrafía, módulos de
balasto y condiciones de empuje, y la herramienta produce el modelo completo de
SAP2000 —geometría, mallado, resortes, patrones de carga y combinaciones— listo
para analizar.

Nace de ingeniería inversa del modelo `ModeloEtabs/MuroContencion.s2k`, cuya
topología reproduce exactamente (172 nudos, 65 frames, 90 shells, 60 resortes).

## Arranque

Doble clic en **`Iniciar.bat`**. Instala dependencias la primera vez, levanta el
servidor local y abre el navegador en <http://127.0.0.1:8777>.

Manual:

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8777
```

Requiere Python 3.10+. Para el camino OAPI hacen falta además Windows, SAP2000
instalado y `comtypes`.

## El ciclo completo, paso a paso

Todo se hace desde la barra superior, de izquierda a derecha. El estado vive en
el navegador: el servidor no guarda nada entre peticiones.

| # | Acción | Qué pasa | Qué mirar |
|---|---|---|---|
| 1 | Llenar el panel izquierdo, o **Cargar datos** con un `.json` guardado antes | El modelo se reconstruye a cada cambio | La pestaña **Perfil del muro** dibuja el muro, la viga en pendiente y cada pila con su longitud |
| 2 | **Actualizar modelo** | Recalcula geometría, empujes y combinaciones | Avisos del constructor en el panel derecho |
| 3 | **Enviar a SAP** | Abre SAP2000 y carga el modelo, sin correrlo | La topología en SAP debe coincidir con la del panel |
| 4 | **Correr y verificar** | Corre el análisis, lee resultados y aplica ACI 318-19 | *Elementos no conformes* debe ser 0; si no, revise el D/C por elemento |
| 5 | Pestaña **Fuerzas de diseño** | Interacción P-M, envolventes de la viga y mapa del muro | Qué combinación gobierna cada componente |
| 6 | Pestaña **Refuerzo** | Las seis vistas y las láminas L-01 / L-02 | Ajuste barras y separaciones en el panel derecho: lo colocado frente a lo requerido, marca a marca |
| 7 | **Despiece DXF / PDF**, **Memoria Word**, **Memoria Excel** | Descargan el juego con los ajustes ya aplicados | Si alguna marca quedó corta, avisa antes de exportar y exporta igual |
| 8 | **Guardar datos** | Baja el `.json` del proyecto, con los ajustes de refuerzo dentro | Es lo que se vuelve a cargar en el paso 1 |

Los pasos 3 y 4 necesitan Windows con SAP2000 y licencia libre. Los demás
funcionan sin SAP; sin verificaciones, la memoria sale con la parte de datos y
los botones de despiece quedan deshabilitados, porque el armado se calcula de
las solicitaciones y no de la geometría.

**Ciclo por script**, cuando ya hay un proyecto definido:
`python proyectos/correr_altos_la_molina.py` hace los pasos 2 a 7 de un tirón y
deja todo en `salidas/`.

Al pulsar **Correr y verificar**, además del Excel se escriben en `salidas/` la
lámina de despiece en DXF, PDF y SVG y la memoria en Word. Los botones de la
barra superior descargan una copia de cada uno.

## Qué hace

**Paneles plegables.** Los dos laterales se ocultan con los botones ◧ ◨ ◻ de la
barra, o con Alt+1, Alt+2 y Alt+0. Plegando ambos, el área de trabajo pasa de
unos 870 px a los 1536 de la pantalla: un 77 % más para mirar diagramas y
despiece. La elección se recuerda en `localStorage`.

Detalle de la rejilla que conviene no romper: los paneles se ocultan con
`display:none`, y un elemento oculto **deja de ser ítem de la rejilla**, así que
los que quedan se corren al hueco anterior —el área de trabajo acababa en la
columna de 0 px—. Por eso `.sidebar`, `.workspace` y `.results` llevan su
`grid-column` fijada.

**Tema.** La interfaz tiene tema claro y oscuro. Arranca siguiendo la preferencia
del sistema y el botón de la barra superior lo alterna; la elección se recuerda en
`localStorage`. Los lienzos se pintan con Canvas 2D, que no entiende `var(--x)`,
así que la paleta se lee del CSS al arrancar y en cada cambio de tema: el color
vive en un solo sitio, `styles.css`.

**Salida.** La pestaña *Fuerzas de diseño* tiene tres vistas, todas alimentadas
por `LAST.checks` sin volver a pedirle nada a SAP:

- **Interacción P-M**: la curva de capacidad de cada zona de refuerzo con la
  demanda de cada elemento de pila encima, y un círculo en el más solicitado.
  La curva se guarda **una por zona**, no una por elemento, porque depende solo
  de la sección.
- **Envolventes de la viga cabezal**: momento, cortante y torsión a lo largo de
  Y, dibujados como escalones —uno por elemento, que es la resolución real del
  modelo— con la combinación que gobierna cada uno.
- **Mapa del muro**: alzado Y-Z con cada shell coloreado por `M22`, `M11` o
  cortante, y las franjas de diseño superpuestas con su acero.

El panel derecho trae además la **planilla de despiece completa**, que se pide a
`/api/design/despiece`: es el mismo cálculo que alimenta la lámina y la memoria,
así que lo que se ve en pantalla y lo que recibe el dibujante no pueden
divergir.

**Refuerzo.** La pestaña *Refuerzo* es donde se revisa y se ajusta el armado
antes de exportar. A la izquierda el dibujo del elemento —corte del conjunto,
arranque, sección y alzado de viga, sección de pila, o la lámina entera—, que
lo genera el servidor con el **mismo motor que produce el DXF**, de modo que lo
que se aprueba en pantalla es literalmente lo que sale al plano. A la derecha,
los controles del elemento y la comprobación **colocado / requerido** marca a
marca.

**Entrada.** Panel izquierdo con geometría de pantalla, pilas y viga cabezal;
materiales; empuje de tierras; sismo; perfil estratigráfico con balasto por
capa; mallado; refuerzo por tramos de pila; y combinaciones de carga editables.

**Dibujo libre.** La pestaña *Perfil del muro* permite activar «Dibujar perfil
libre» y editar la corona arrastrando nodos (doble clic añade, clic derecho
elimina). La malla es **mapeada**: todas las columnas de shells se dividen en el
mismo número de filas, de modo que los nudos conforman aunque la corona sea
inclinada o escalonada. El empuje se evalúa contra la corona **local** de cada
abscisa, así que una corona variable da automáticamente el diagrama correcto en
cada sección.

**Salidas.**

| Botón | Resultado |
|---|---|
| Descargar .s2k | Archivo de texto de SAP2000. Se importa con *File → Import → SAP2000 .s2k Text File* |
| Memoria Excel | Datos, coeficientes, resultantes de empuje, balasto y topología |
| Guardar / Cargar datos | Proyecto en JSON, para versionar y reutilizar |
| Enviar a SAP | Construye el modelo en SAP2000 por OAPI y lo guarda como `.sdb` en `salidas/` |
| Correr y verificar | Además corre el análisis, extrae envolventes y aplica las verificaciones ACI 318 |

## Cómo se modelan las cargas

En vez de aplicar `K·γ` sobre un patrón de junta lineal en Z, la herramienta
carga en el *joint pattern* **la presión real en kPa nodo a nodo** y aplica una
presión superficial unitaria. Con eso, el mismo esquema de cargas cubre relleno
estratificado, nivel freático y coronas inclinadas sin casos especiales.

Patrones que genera según corresponda:

- `SUELO` — empuje efectivo del relleno, con `K` de Rankine, Coulomb o impuesto.
- `SOBRECARGA` — `K·q` uniforme sobre la altura.
- `AGUA` — presión hidrostática bajo el nivel freático (el empuje del suelo pasa
  automáticamente a peso sumergido bajo ese nivel).
- `SISMO_SUELO` — incremento `ΔKae = Kae − Ka` por Mononobe-Okabe, con
  distribución triangular invertida (resultante a 2H/3 sobre la base), uniforme
  o triangular.
- `DEAD` — peso propio.

**Convenio de signos.** Los shells se generan con el orden de nudos
inferior-izq → inferior-der → superior-der → superior-izq, con lo que el eje
local 3 apunta a **+X** y la cara `Top` mira al trasdós. Una presión positiva
sobre `Top` empuja hacia **−X**, que es el sentido del empuje del relleno.

## Balasto

**Apoyos de la pila.** El fuste no lleva ninguna restriccion: su unica rigidez
es el balasto lateral, que es justo lo que representa el resorte. La punta sí
lleva restriccion, y **solo vertical (U3)** —`piles.tip_restraint`, activo por
defecto—, de modo que el apoyo en el estrato competente es rigido a asiento pero
la pila sigue girando y flectando libremente.

Con la opcion apagada la punta vuelve a llevar el resorte vertical `kv` y el
modelo no tiene ninguna restriccion, que es como esta el `.s2k` original; por eso
`reference_project()` la apaga y la prueba de regresion sigue contrastando contra
el modelo de partida.

Verificado contra SAP: seis nudos restringidos, todos a la cota de punta, solo
U3, y la reaccion vertical total iguala el peso propio con error nulo.

Los resortes laterales de pila se calculan nodo a nodo como
`k = ks_h · D · L_trib`, con `ks_h` del estrato correspondiente a la cota y
`L_trib` la media de los semisegmentos adyacentes. El resorte de punta es
`ks_v · π D²/4`, o un valor impuesto.

Por defecto no se pone resorte lateral en la cabeza de pila (suelo excavado al
frente); es una casilla del panel.

## Verificaciones (ACI 318)

- **Pilas**: diagrama de interacción P-M circular por compatibilidad de
  deformaciones, con `φ` variable según la deformación neta de tracción y tope
  `0.80·φ·Po`. Cortante según 22.5 con `bw = D`, `d = 0.8 D`.
- **Viga cabezal**: flexión rectangular, cortante con estribos y **diseño por
  torsión** completo (22.7). En el modelo de referencia la torsión sale de
  385 kN·m frente a un umbral de 50 kN·m: no es despreciable, porque la viga
  recibe el momento de vuelco de la pantalla. Véase *Torsión* más abajo.
- **Pantalla**: flexión por metro de ancho en ambas direcciones a partir de
  `M11`/`M22`, con `As,min = 0.0018·b·h`, y cortante en una dirección con el
  cortante transversal del shell (`V13`/`V23`), no con las fuerzas de membrana.
  El dimensionado se hace por **franjas de diseño** y con el momento en la cara
  del apoyo; véase *Franjas* más abajo.

El diseño a flexión itera `φ` —área requerida y `φ` son interdependientes cuando
la sección cae en transición— y rechaza secciones sobre-reforzadas (`εt < 0.004`)
o que no alcanzan. Cuando la sección no da de sí no existe un «As requerido»:
ningún armado permitido equilibra `Mu`. En ese caso se reporta el tope
`As_max` (el de `εt = 0.004`), la capacidad `φMn` que se alcanza con él y un
`D/C > 1` que mide el déficit real de sección, con `limitada_por_seccion = true`.

### Torsión de la viga cabezal

La torsión de la viga cabezal es de **equilibrio**: nace del voladizo de la
pantalla y no tiene camino alterno, así que no se puede redistribuir con 22.7.5
(la opción `compatibility` existe, pero está desactivada por defecto). El diseño
sigue ACI 318-19 y entrega lo que hace falta para dibujar:

| Concepto | Referencia |
|---|---|
| `Aoh`, `ph`, `Ao = 0.85·Aoh` al eje del estribo cerrado | 22.7.6.1 |
| Límite de la sección combinada V+T | 22.7.7.1(a) |
| `At/s` por rama, con `θ = 45°` | 22.7.6.1(a) |
| `(Av + 2At)/s` y su mínimo | 9.6.4.2 |
| `Al` longitudinal y su mínimo | 22.7.6.1(b), 9.6.4.3 |
| `s ≤ mín(ph/8, 300 mm)` | 9.7.6.3.3 |
| Barras del perímetro a ≤ 300 mm, `db ≥ 0.042·s` | 9.7.5.1 |

Para la viga de referencia (0.80 × 1.00 m, f'c 21 MPa, Tu 385 kN·m) sale
`At/s = 1179 mm²/m` por rama, `Al = 3713 mm²` y estribos cerrados #4 @ 100 mm
con 19 barras #5 en el perímetro, con la sección al 0.69 del límite de 22.7.7.1.
Todo ello contrastado a mano en `tests/test_design.py`.

### Franjas de diseño de la pantalla

Dimensionar toda la pantalla con el máximo absoluto de `M11`/`M22` sobrearma la
corona y no es defendible ante revisión. En su lugar la altura se parte en
franjas (`mesh.wall_design_strips`, 3 por defecto) y cada una se arma con su
propia solicitación, promediada sobre los elementos de la franja —que es
exactamente lo que significa una franja de diseño—.

Además se aplica ACI 318 9.4.2.1, que permite diseñar con el momento en la
**cara del apoyo** y no en su eje:

- en vertical, la cara es el borde superior de la viga cabezal
  (`z_base + h_viga/2`);
- en horizontal, el borde de la pila (`y_pila ± D/2`).

Si la cara cae dentro del primer shell, no se reduce nada: el promedio del
elemento ya representa la franja y bajar más sería inventar una precisión que la
malla no da. El reporte trae siempre las tres cifras —eje, cara y vano— para que
la reducción sea auditable.

**Sobre los momentos del muro.** SAP devuelve un valor por nudo de esquina de
cada shell. Los valores de esquina sobre un apoyo puntual son singularidades
numéricas: crecen indefinidamente al refinar la malla y no son solicitación de
diseño. La herramienta promedia los nudos de cada elemento para dimensionar y
reporta el pico crudo por separado. En el modelo de referencia la diferencia es
grande: `M22` pasa de 973 kN·m/m en el pico nodal a 620 kN·m/m promediado.

Las verificaciones exponen, además de los resultados ya digeridos, tres cosas
que la interfaz necesita para dibujar: `interaccion` (curva y demanda por zona),
`envolventes` (min, max y **combinación que gobierna** cada componente, elemento
a elemento) y `muro.elementos` (el valor por shell). Antes se calculaban y se
descartaban dentro de `verify()`.

El D/C del muro a flexión vale 1.00 por construcción, porque ahí se *calcula* el
acero necesario en lugar de comprobar uno dado; el único D/C con significado es
el de cortante, que no lleva refuerzo transversal. Por eso el resumen expone
`ratio_cortante_muro` y no un D/C de flexión.

## Estructura

```
app/
  core/
    params.py     esquema de entrada (pydantic) y coeficientes Ka/K0/Kae
    model.py      modelo estructural neutro, con fusión de nudos por coordenada
    soil.py       perfil de presiones y módulos de balasto
    builder.py    parámetros -> modelo: mallado, resortes, cargas, grupos
  exporters/
    s2k.py        escritor de .s2k (CRLF, 240 col, continuación con ' _')
    oapi.py       driver COM de SAP2000
    drawing.py    escena de dibujo neutra (primitivas, capas, cotas) y SVG
    dxf.py        escritor de DXF R12 desde la escena
    pdfout.py     escritor de PDF vectorial multipágina, sin dependencias
    raster.py     rasterizador a PNG con Pillow, para las figuras de la memoria
  results/
    design.py     verificaciones ACI 318, incluido el diseño por torsión
    extract.py    envolventes, franjas de diseño y orquestación del análisis
    rebar.py      despiece: de las áreas de acero a barras reales
    detailing.py  láminas: planta, alzado, cortes, detalles, planilla y gráficas
    report.py     resultados en Excel
    memoria.py    memoria de cálculo en Word
  web/static/     interfaz (HTML + CSS + JS, sin dependencias externas)
  main.py         backend FastAPI
tests/
  test_reference.py   reproduce el modelo original y valida el .s2k
  test_design.py      torsión, flexión, franjas, casos modal/P-Delta y Excel
  test_despiece.py    despiece, juego de láminas en DXF/SVG/PDF y memoria en Word
  test_pilas.py       pilas de distinta profundidad, armado y análisis pila a pila
  test_sap_oapi.py    integración real contra SAP2000 por OAPI
salidas/          .sdb y .xlsx generados por el camino OAPI
```

## El camino OAPI

El driver materializa el modelo escribiendo el `.s2k` y abriéndolo con
`SapModel.File.OpenFile()`, en lugar de reconstruirlo llamada a llamada. Así el
camino OAPI y el de importación manual producen exactamente el mismo modelo, y
no hay dos definiciones de secciones y cargas que mantener sincronizadas. La API
nativa se usa para lo que el `.s2k` no cubre: correr el análisis, leer
resultados y lanzar el diseño.

El diseño de concreto de SAP se lanza con `run_concrete_design()`, que prueba
los nombres de código en orden (`ACI 318-19`, `-14`, `-11`, `-08`) porque
cambian entre versiones, y devuelve el que SAP aceptó. Dos trampas medidas
contra la instalación real:

- Las funciones de **diseño** usan `ItemType` (grupo = 1), no el `ItemTypeElm`
  de las de resultados (grupo = 2).
- Aun con el enum correcto, **la consulta por grupo devuelve código 1**. Hay que
  leer **objeto a objeto**; como el `.s2k` conserva las etiquetas, los ids del
  modelo neutro valen como nombres de frame.

En las **pilas** el contraste funciona y es bueno: sobre el modelo de
referencia SAP da un D/C P-M-M máximo de 0.968 y el cálculo propio 0.96.

En la **viga cabezal** hace falta un paso más. SAP decide si una sección de
concreto se diseña como viga o como columna por el tipo de **armadura** que
tiene definida, no por la orientación del miembro. El `.s2k` escribe la tabla
`FRAME SECTION PROPERTIES 05 - CONCRETE BEAM`, pero eso no cambia ese indicador:
la viga acababa diseñándose por interacción P-M-M, que **no mira la torsión**.

`SapDriver.set_beam_sections` lo arregla llamando a `PropFrame.SetRebarBeam`
después de importar, con las áreas a cero para que SAP **diseñe** el refuerzo en
lugar de comprobar uno impuesto. Con eso SAP devuelve diseño de viga —45
estaciones— y reporta `TLArea`/`TTArea`, y el contraste sale solo:

| | Cálculo propio | SAP2000 | Diferencia |
|---|---|---|---|
| `Al` por torsión | 4273 mm² | 4311 mm² | −0.9 % |
| `At/s` por rama | 1177 mm²/m | 1183 mm²/m | −0.5 % |

Son dos implementaciones independientes de ACI 318-19 22.7 sobre el mismo
modelo. `test_sap_oapi.py` falla si la diferencia pasa del 15 %.

## Despiece de refuerzo

Una vez corrido el análisis, las áreas de acero se convierten en **barras
reales**: `rebar.py` elige diámetros y separaciones, calcula longitudes de
desarrollo, ganchos y traslapos según el capítulo 25 de ACI 318-19, trocea las
corridas largas en barra comercial de 12 m con solape clase B, y arma la
planilla con marca, diámetro, forma, dimensiones de doblado, longitud, cantidad
y peso.

Dos criterios que conviene tener claros al leer la planilla:

- **La longitud de corte lleva la extensión geométrica del gancho, no su
  longitud de desarrollo.** `ldh` es una comprobación de anclaje —debe caber en
  el elemento que recibe la barra—, no un tramo de acero que se corta. La
  extensión (12·db a 90°, 6·db a 135°) sí se corta.
- **Las zonas de pila solapan entre sí.** Cada zona baja hasta traslapar clase B
  con la de abajo; la inferior no, porque es la que recibe ese solape.

En el muro se aplica ACI 318 11.7.2.3: con espesor mayor de 250 mm el acero va
en dos capas, la de diseño en la cara traccionada y el mínimo repartido en la
opuesta.

### Un motor de dibujo, tres formatos

`drawing.py` define una **escena neutra** —primitivas en metros, por capas, con
cotas y directrices— y de ella salen los formatos, igual que el modelo
estructural sale en `.s2k` y por OAPI desde una sola representación:

| Formato | Para qué | Cómo |
|---|---|---|
| **DXF R12** | el dibujante, que monta el plano encima sin redibujar | `dxf.py`, ASCII, **en metros y a escala 1:1**, capas CONCRETO / REFUERZO / ESTRIBOS / COTAS / TEXTO / TABLA |
| **PDF** | revisar e imprimir a escala | `pdfout.py`, PDF 1.4 vectorial multipágina, sin dependencias |
| **SVG** | mirar en el navegador, incrustar | `drawing.to_svg`, en milímetros de papel |
| **PNG** | las figuras de la memoria | `raster.py`, con Pillow y supermuestreo ×3 |

R12 a propósito: lo abre cualquier CAD sin discusión y no necesita tablas de
objetos ni clases. Todo el archivo usa el mismo final de línea —un DXF con
finales mezclados lo rechazan algunos lectores—.

**El DXF va en metros y a escala 1:1; el PDF y el SVG llevan la lámina
compuesta.** No es lo mismo: una lámina es papel, sus coordenadas son milímetros
de hoja y dentro el muro está a 1:20, así que medir sobre ella da 465 en vez de
9.30. El dibujante necesita lo contrario: geometría a tamaño real sobre la que
acotar y montar su propio formato. `detailing.modelo()` arma esa versión —cada
vista a 1:1, y solo las tablas y las notas, que nacen en milímetros de papel,
escaladas a 1:25— y es lo que sale por `/api/export/despiece.dxf`. La prueba
comprueba que una pila de Ø1.00 mide 1.00 en el archivo.

### Juego de láminas

No es una lámina suelta sino un **juego de A1 numeradas**, cada dibujo a su
escala normalizada. Normalmente son **dos**:

| Lámina | Contenido |
|---|---|
| **L-01** | Planta de replanteo con ejes y burbujas numeradas, alzado del muro con las franjas de refuerzo, notas generales y tabla de refuerzo por franja |
| **L-02** | Corte transversal, sección de pila, sección de viga, alzado de la viga cabezal, **detalle del arranque** de la pantalla —el nudo que decide el despiece— y, en la banda inferior, la planilla de aceros con croquis de doblado, resumen por diámetro y cuadro de materiales |

La planilla de un muro corriente ocupa alrededor de un cuarto de pliego, así que
cabe con las secciones y no hay motivo para gastar una hoja entera en ella. La
banda inferior **se ajusta a lo que ocupa la planilla** y los dibujos se reparten
el resto; si el despiece crece tanto que no cabría ni con filas de 5 mm —el
mínimo legible en una A1—, se separa solo en una **L-03** en vez de apretar las
filas hasta que no se lean. `detailing.n_laminas()` responde cuántas hay sin
dibujarlas, y la interfaz enseña el botón de la tercera solo cuando existe.

**El texto se mide en milímetros de papel, no en unidades de modelo.** Una
sección a 1:40 heredaba rótulos de metro y medio de modelo, es decir 1.5 mm en
la hoja: legibles en pantalla, invisibles impresos. `Scene.merge` acota la
altura del texto ya escalado y `_colocar` la fija entre 2.6 y 7 mm, de modo que
ninguna vista baja del mínimo legible en una A1 sea cual sea su escala. Los
rótulos de vista se reducen si no caben en su caja, y `bbox()` tiene en cuenta
el alineado del texto —un rótulo centrado ocupa media cadena a cada lado, no
toda a la derecha—.

Las **notas generales** son las de un plano estructural de verdad: normativa,
materiales, recubrimientos por elemento, longitudes de traslapo **calculadas
para cada diámetro presente**, ganchos y advertencias de ejecución. El cajetín
lleva número de lámina, escalas, revisión, fecha y casilla de firma, más el
ingeniero responsable con su **matrícula profesional** (`info.license`) y el
cliente. Un plano estructural firmado lleva la matrícula junto al nombre.

El **PDF sale multipágina**, una lámina por hoja, que se lee e imprime mucho
mejor. El DXF y el SVG llevan todas en fila, como se montan en CAD.

Detalle de composición que no conviene deshacer: el alzado del muro es casi
cuadrado —6 m de pantalla sobre 10 de pila—, así que se lleva toda la altura de
la columna izquierda, y la planta, que es ancha y baja, va arriba a la derecha.
Al revés queda medio pliego en blanco.

## Ajuste del refuerzo

El armado que calcula la herramienta es una *propuesta*. `rebar_overrides`, que
vive **dentro del proyecto**, recoge lo que el ingeniero decide imponer:

| Ámbito | Se puede fijar |
|---|---|
| Pantalla, por franja | diámetro y separación, vertical y horizontal |
| Pantalla, global | barra vertical y horizontal por defecto |
| Viga cabezal | diámetro y número de barras arriba y abajo; estribo y su paso; barra y número del longitudinal por torsión |
| Pilas | por zonas, en el panel de entrada de siempre |

Que viva en el proyecto y no en la petición es deliberado: así se guarda con
«Guardar datos» y llega solo a las láminas, al DXF, al PDF, al Excel y a la
memoria. **No hay dos versiones del despiece circulando.**

Cada campo vacío sigue el valor recomendado, que aparece en gris en el control.
La recomendación se recalcula para el diámetro elegido —con una #7 hace falta
menos densidad que con una #5 para la misma área, así que el paso sugerido
crece—, de modo que la sugerencia sigue siendo útil después de cambiar de barra.

Cada marca lleva su **área requerida y su área colocada**, y el panel las
enfrenta: si un ajuste deja acero por debajo de lo necesario, la marca sale en
rojo y aparece en `marcas_insuficientes`. La exportación **no se bloquea** —si se
decide sacar planos con un armado corto, es una decisión del ingeniero— pero se
avisa al pulsar, y el aviso queda también en el panel de resultados.

## Memoria de cálculo

`memoria.py` produce un `.docx` con python-docx pensado para firmarse: no un
volcado de resultados, sino el desarrollo con las fórmulas y los números
sustituidos —coeficiente de empuje, incremento sísmico, diseño por torsión paso
a paso, franjas de la pantalla— de modo que un revisor pueda seguir el cálculo
sin abrir el modelo.

Ocho capítulos: objeto, datos de partida, empujes, modelo, verificación de cada
elemento, despiece, conclusiones y un **anexo con las envolventes** de cada
elemento y la combinación que gobierna cada componente. Lleva **índice** —un
campo `TOC` que Word rellena al actualizarlo—, encabezado con el nombre del
proyecto y pie con numeración de páginas.

**Figuras.** Word no admite SVG ni PDF desde `python-docx`, solo mapas de bits,
así que `exporters/raster.py` dibuja la misma escena con Pillow —supermuestreo
×3 y reducción, que es la forma barata de suavizar líneas y texto— y la
incrusta. Van cinco: planta de replanteo, diagrama de empujes por componentes,
interacción P-M de la zona más solicitada con la demanda de cada pila encima,
corte transversal armado y detalle del arranque. Una figura que falle no tumba
la memoria: se omite y el documento sigue.

Sin verificaciones sale igualmente, con los capítulos que no dependen del
análisis. El despiece, en cambio, exige haber corrido el modelo: sale de las
solicitaciones reales, no de la geometría.

## Un muro real: Altos de La Molina

`proyectos/altos_la_molina.py` traduce el estudio geológico-geotécnico 017-2026
(IDEAR+, Guarne, Antioquia) a dos proyectos de la herramienta, y
`proyectos/correr_altos_la_molina.py` corre el ciclo entero —SAP, resultados,
diseño, despiece, láminas y memoria— y contrasta lo obtenido contra las tablas
que el estudio le entrega al diseñador estructural.

Es un muro pantalla sobre viga cabezal y pilas de 17.00 m de desarrollo, con la
corona horizontal y el fondo de la excavación bajando 0.2647 m/m, partido por
una junta de contracción en la abscisa K0+011.00. **Cada tramo se modela por
separado**, que es lo que dice el propio estudio: la junta los vuelve dos
estructuras independientes.

| | Tramo 1 | Tramo 2 |
|---|---|---|
| Abscisas del muro | K0+001.70 a K0+011.00 | K0+011.00 a K0+017.00 |
| Altura del vástago | 0.45 → 2.91 m | 2.91 → 4.50 m |
| Vástago | 0.25 → 0.35 m | 0.30 → 0.50 m |
| Viga cabezal | 1.00 × 0.45 m | 1.20 × 0.60 m |
| Pilas | 3 × Ø1.00, L = 4.00 / 5.50 / 6.00 m | 2 × Ø1.20, L = 7.00 / 8.50 m |

### Lo que hizo falta añadir

Este primer muro real pidió cuatro cosas que el modelo no sabía decir, y las
cuatro son generales, no de este proyecto:

| Qué | Dónde | Por qué |
|---|---|---|
| **Pilas de distinta longitud** | `piles.z_bots` | Un corte de profundidad variable no puede llevar todas las pilas iguales |
| **Base del muro en pendiente** | `wall.base_profile`, ya existía, ahora la **viga cabezal y las cabezas de pila la siguen** | La viga se desplanta en el fondo de la excavación, que baja con el alineamiento |
| **Vástago acartelado** | `wall.thickness_top` | El espesor va de corona a arranque; diseñar la corona con el espesor del arranque deja la corona corta de acero |
| **Voladizos de la viga cabezal** | `cap_beam.overhangs` | El estudio optimizó el voladizo en 0.207·L, y antes la viga sólo iba de pila a pila |

El balasto se da como `soil.nh`, el módulo de reacción horizontal de Matlock y
Reese: el resorte crece con la profundidad **bajo la cabeza de cada pila**, que
es como lo entrega un estudio geotécnico y lo único correcto cuando las cabezas
están a distinta cota.

El diagrama de presiones no se recalcula: el estudio lo obtiene por cuña de
prueba sobre el perfil real, así que se reproduce con `K` impuesto y la
sobrecarga de 12 kPa. Sale a menos del 0.5 % de las tablas 20 y 40.

### Dimensionamiento del refuerzo

`results/sizing.py` es la pieza que faltaba: el resto de la herramienta
*verifica* un armado propuesto, y esto lo *busca*. Recorre una escalera de
(número de barras, diámetro) dentro de ρ entre 0.5 % y 4 %, se queda con la
primera que cubre la demanda y, entre opciones de área parecida, prefiere la de
menos barras —28#8 se coloca y se vibra mejor que 36#7 para la misma área—.

No hace falta volver a correr SAP entre tanteos: la rigidez sale de la sección
bruta, de modo que cambiar barras no cambia las solicitaciones.

Admite un **piso de momento por zona**. Sirve para no quedarse por debajo del
estudio geotécnico: el mecanismo de pila larga de Broms pide más que el modelo
elástico sobre resortes, y esa demanda la fija el geotecnista. Las pilas de
este muro se armaron para la envolvente de las dos.

## Pilas de distinta profundidad

En un corte de profundidad variable las pilas no son intercambiables: cada una
tiene su longitud, su cota de cabeza y su demanda. La herramienta las trata una
por una de punta a punta.

| Qué | Dónde |
|---|---|
| Profundidad de cada pila | `piles.z_bots`, o el panel **Profundidad de cada pila** |
| Cabeza en la base del muro | automática cuando `wall.base_profile` va en pendiente |
| Balasto bajo la cabeza de *cada* pila | `soil.nh` (Matlock y Reese), `ks_h = n_h·z/D` con z medido desde su propia cabeza |
| Armado propio de una pila | `piles.zones[].piles`, o la columna **Pilas** del editor de zonas |

Una zona con `piles` fijado **manda sobre la general** que ocupe la misma cota,
de modo que se puede partir de un armado común y afinar sólo las pilas que lo
necesiten. Las zonas se recortan solas en la punta de cada pila: una zona
definida hasta −13 m no aparece en una pila que termina en −7.

### Qué sale pila a pila

- **`checks["pilas_resumen"]`**: una ficha por pila con geometría, Pu/Mu/Vu,
  la cota del momento máximo, el D/C que gobierna y sus zonas. Se ve en la app
  (tabla *Pilas, una por una*), en la hoja **PilasResumen** del Excel y en la
  memoria.
- Cada registro de `checks["pilas"]` lleva su campo `pila`, de modo que el
  detalle elemento a elemento se puede agrupar sin adivinar por coordenadas.
- El **despiece** recorre pila por pila y junta después los tramos idénticos:
  un grupo de pilas iguales sigue dando una marca, y la que tiene armado propio
  queda separada y rotulada con su número.
- El **plano** dibuja una sección por armado distinto, con las pilas a las que
  pertenece, y el alzado rotula la longitud y la cota de punta de cada una.

### Dimensionamiento pila a pila

`sizing.dimensionar_pilas(..., por_pila=True)` da primero a cada pila su propio
juego de zonas y luego arma cada una para lo suyo. En el muro de Altos de La
Molina eso baja la primera pila del tramo 1 de 14#8 —lo que pedía la tercera— a
14#6, que es lo que pide ella.

El parámetro `pisos` impone un **momento mínimo por pila**. Es como se cubre la
demanda del estudio geotécnico cuando su mecanismo de pila larga pide más que el
modelo elástico sobre resortes.

La escalera de tanteo se queda entre 10 y 20 barras cuando puede: ni 6 barras
gordas ni 26 finas se arman igual de bien, aunque den la misma área.

## Casos de análisis

Además del estático lineal, `analysis` permite dos casos, ambos **desactivados
por defecto**: con los dos en `false` el `.s2k` sale byte a byte igual al del
camino ya validado, y las tablas nuevas solo se emiten cuando se piden.

- **Modal** (`analysis.modal`): caso por vectores propios, con la masa tomada
  del peso propio a través de la fuente de masa por elementos. Se leen periodos
  y masa participante; si la acumulada no llega a 0.90 la interfaz lo avisa.
- **P-Delta** (`analysis.pdelta`): caso estático no lineal con no linealidad
  geométrica P-Delta sobre la carga sostenida (1.2 DEAD + 1.6 SUELO por
  defecto, editable en `analysis.pdelta_factors`).

Quedan fuera las **etapas constructivas** y los **resortes de solo compresión**.
Llegaron a implementarse y se retiraron a propósito:

- Los resortes de balasto son **bidireccionales**, que es el modelo estándar: dan
  rigidez lateral en X e Y para que la pila trabaje contra el suelo. La variante
  de solo compresión —que modela el despegue del suelo en el lado pasivo— es un
  refinamiento de segundo orden que solo pesa con desplazamientos grandes o carga
  cíclica, y obliga a enlaces no lineales y a nudos de tierra restringidos que
  ensucian el modelo.
- El caso por etapas se importaba y se leía de vuelta bien, pero **SAP2000 v27.1.0
  Advanced solo resuelve casos por etapas de UNA etapa**: con dos o más los excluye
  en silencio al crear el modelo de análisis. Bisecado hasta un repro mínimo; no
  depende de los grupos, las cargas, las duraciones ni la estabilidad del modelo
  parcial. Además, un caso por etapas es no lineal y no se puede combinar
  linealmente, así que integrarlo habría obligado a replantear las verificaciones.

Lo aprendido —esquemas de las tablas del `.s2k`, el enlace de dos nudos, el límite
de una etapa— está anotado por si algún día se retoma.

## Validación contra teoría

Con el modelo corrido en SAP, los cortes de sección y las reacciones se
contrastan con el cálculo cerrado:

| Magnitud | Teoría | SAP | Error |
|---|---|---|---|
| Peso propio total (`DEAD`) | 3322.04 kN | 3322.04 kN | 0 % |
| Empuje estático `0.5·K·γ·H²·L` | 1428.00 kN | 1428.00 kN | 0 % |
| Incremento sísmico `0.5·ΔKae·γ·H²·L` | 426.72 kN | 426.72 kN | 0 % |
| Momento del empuje en la base `P·H/3` | 2856.0 kN·m | 2856.0 kN·m | 0 % |
| Momento sísmico en la base `P·2H/3` | 2741.8 kN·m | 2741.8 kN·m | 0 % |
| Peso propio con corona inclinada | 1587.60 kN | 1587.60 kN | 0 % |
| Empuje con freático sobre corona inclinada | 1230.19 kN | 1229.00 kN | 0.097 % |

La suma de reacciones de los resortes coincide con `BaseReact` en todos los
casos: el equilibrio cierra. El 0.097 % del último caso es discretización de
malla en el quiebre del nivel freático, que cae dentro de un elemento.

## Hallazgos sobre el modelo original

Revisando `MuroContencion.s2k` aparecieron cuatro cosas que el generador corrige:

1. Los grupos `MMAX`, `MMAX_LOSA1` y `MMAX_LOSA2` estaban **vacíos**, así que
   los tres *section cuts* definidos no devolvían nada. Aquí los grupos se
   asignan automáticamente (`MURO`, `MURO_BASE`, `PILAS`, `PILA_nn`,
   `VIGA_CABEZAL`, `APOYOS`).

   Llenar los grupos no basta: probándolo contra SAP resultó que **un corte por
   grupo devuelve cero si el grupo solo contiene elementos**. SAP calcula la
   resultante como las fuerzas que cruzan los *nudos* del grupo hacia lo que
   queda fuera, así que el grupo debe incluir los elementos de un lado del corte
   y los nudos del plano de corte. Por eso hay dos grupos dedicados,
   `CORTE_MURO_BASE` y `CORTE_PILAS_CABEZA`, con sus nudos dentro.
2. Las secciones `LOSA50` y `04_VC_2.10x0.60` estaban definidas y sin usar.
3. La presión dinámica se aplicaba con presión negativa sobre patrón negativo
   (doble negativo). Aquí los valores del patrón son la presión física en kPa.
4. El modelo no tiene ningún *restraint*: la estabilidad vertical depende de los
   seis resortes de punta. Es válido, pero conviene contrastar la reacción
   vertical con el peso propio en cada corrida — para eso está el grupo
   `APOYOS` y el campo `reaccion_vertical_total`.

## Equivalencia con el modelo original

```
python tests/test_reference.py
```

Reproduce el modelo entregado y comprueba topología, empujes
(30.6 kPa en la base con `K·γ = 5.1`; 16.32 kPa en corona con `ΔKae·γ = 2.72`),
resortes y formato del `.s2k`.
