# Notas para Claude

Contexto que Claude Code carga solo al abrir este repositorio. Sirve para
retomar el desarrollo en cualquier máquina sin volver a descubrir lo que ya
costó descubrir una vez.

El **README** documenta la arquitectura, los criterios de cálculo y la
validación: no repetir nada de eso aquí. Esto son las decisiones, las trampas y
lo que queda abierto.

---

## Qué es

Generador paramétrico de modelos SAP2000 de **muros de contención sobre pilas
con viga cabezal**. Nació de parametrizar `ModeloEtabs/MuroContencion.s2k` y
hoy cubre el ciclo entero: modelo → SAP por OAPI → resultados → verificación
ACI 318-19 → dimensionamiento del refuerzo → despiece → planos → memoria.

Validado contra **SAP2000 v27.1.0 Advanced**: error 0 % frente al cálculo
cerrado en peso propio, empuje estático, incremento sísmico y momentos en la
base.

## Cómo se trabaja aquí

- **Todo en español**: respuestas, código, comentarios y documentación.
- **Sin tildes ni eñes en el código** (identificadores, comentarios, nombres de
  sección): el `.s2k` y SAP no los tragan bien. El texto de cara al usuario
  —interfaz, README, mensajes, rótulos de plano— sí lleva acentos.
- Unidades internas **kN, m, grados**. Cotas Z absolutas.
- La prioridad es **velocidad de iteración**, no exhaustividad.
- Al reportar un hallazgo, dar el **número y el contraste contra teoría**, no la
  impresión general. Los problemas reales del trabajo previo se señalan; se
  agradecen.

## Arranque y pruebas

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8777   # o Iniciar.bat

python tests/test_reference.py   #  19 — reproduce el modelo original
python tests/test_design.py      #  97 — torsión, flexión, franjas, Excel
python tests/test_despiece.py    # 122 — despiece, láminas, DXF/SVG/PDF, memoria
python tests/test_pilas.py       #  68 — pilas de distinta profundidad
python tests/test_sap_oapi.py    # integración real (abre SAP2000)
```

Las cuatro primeras no necesitan SAP. **306 comprobaciones**; deben quedar todas
en verde antes de dar nada por terminado.

Ciclo completo de un proyecto real: `python proyectos/correr_altos_la_molina.py`.

## Trampas del entorno (Windows)

- **`pkill -f uvicorn` no mata el proceso en Git Bash.** Para liberar el puerto:
  `Get-NetTCPConnection -LocalPort 8777 -State Listen | Select -Expand OwningProcess -Unique | ForEach { Stop-Process -Id $_ -Force }`
- **Canalizar un script largo por `tail`/`head` retiene toda la salida** hasta
  que termina y parece colgado. Usar `python -u script.py > salida.log 2>&1 &` y
  leer el log.
- **El heredoc de Bash procesa las barras invertidas aunque el delimitador vaya
  entre comillas.** Un `"\n"` dentro del script llega a Python como salto de
  línea real y corrompe el archivo. Para editar de forma programática: escribir
  el script a un archivo y ejecutarlo con `python archivo.py`. Esto ya ha costado
  tres archivos rotos.
- Los estáticos se sirven con `no-store`, pero tras tocar `app.js` o
  `styles.css` conviene recargar en duro.

## Trampas del OAPI de SAP2000

Ninguna se deduce de la documentación y todas costaron una iteración.

- **comtypes rellena los parámetros de salida.** A `Results.FrameForce` y
  compañía solo se les pasan los argumentos de **entrada**. El valor devuelto es
  a veces lista y a veces tupla: comprobar `isinstance(ret, (tuple, list))`.
- **Un section cut por grupo devuelve cero si el grupo solo contiene
  elementos.** Tiene que incluir los elementos de un lado del corte **y los
  nudos del plano de corte**.
- **SAP se cierra al soltar la última referencia COM.** Hay que cachear la
  sesión; abrir y cerrar el driver en cada petición cierra el modelo del usuario
  y paga ~20 s de arranque.
- **`File.OpenFile()` acepta `.s2k` y `.$2k`**, así que el modelo se materializa
  escribiendo texto y abriéndolo. Mucho más robusto que encadenar 40 setters.
- **Las funciones de DISEÑO usan otro enum que las de resultados**: resultados
  `ItemTypeElm` (grupo = 2), diseño `ItemType` (grupo = **1**). Y aun con el
  enum correcto, la consulta por grupo devuelve código 1: hay que iterar
  **objeto a objeto** (`ItemType = 0`).
- **SAP decide viga vs columna por el TIPO DE ARMADURA de la sección**, no por
  la orientación. Escribir la tabla de viga en el `.s2k` no cambia el indicador:
  hay que llamar `PropFrame.SetRebarBeam` por OAPI **tras** el `OpenFile`
  (`SapDriver.set_beam_sections`). Un `SetRebarBeam` que devuelve 1 suele ser un
  **nombre de sección mal escrito**, no un rechazo de SAP.
- Un `StartDesign()` que devuelve 0 **no garantiza** resultados para el miembro
  consultado; mirar el `n` de la lectura.
- Los momentos de shell en nudos de esquina sobre un apoyo puntual son
  **singularidades**: crecen al refinar la malla. Se promedia por elemento y el
  pico crudo se guarda aparte.
- **`ApplicationStart()` devuelve -1 cuando el pool de licencias está lleno.** No
  es un fallo del código. Se confirma lanzando `SAP2000.exe` a mano: aparece un
  diálogo *SAP2000 License Message*, «Status 484. All N licenses in use». Hay
  que liberar una licencia.
- Un `.s2k` con 20 o más errores abre un **diálogo modal que congela el COM**.
  Para depurar, generar un modelo mínimo.
- Los esquemas de tabla se preguntan con `DatabaseTables.GetAllFieldsInTable`;
  no hace falta adivinarlos.
- **Construcción por etapas: SAP2000 v27.1.0 resuelve casos de UNA sola etapa.**
  Con dos o más los excluye en silencio; `RunAnalysis` devuelve 0 y el caso
  queda en estado 1. Bisecado: no son los grupos, ni el operador de carga, ni
  las duraciones, ni la licencia. La función se implementó y **se retiró**.

## Decisiones que conviene no deshacer

- **Los ajustes de refuerzo viven en `project.rebar_overrides`**, dentro del
  proyecto y no en la petición. Así se guardan con «Guardar datos» y llegan
  solos a lámina, DXF, PDF, Excel y memoria: no hay dos despieces circulando.
- **La longitud de corte de una barra lleva la extensión geométrica del gancho,
  no la `ldh`.** `ldh` es una comprobación de anclaje, no un tramo que se corta.
- **Las zonas de pila solapan entre sí clase B**; la inferior no, porque es la
  que recibe el solape.
- **El DXF va en metros a escala 1:1** (`detailing.modelo`); el PDF y el SVG
  llevan la lámina compuesta, que es papel. Una lámina no se puede medir: dentro
  el muro está a 1:20.
- **El texto se mide en milímetros de papel.** `_colocar` acota lo que viene de
  una vista escalada a [2.6, 7.0] mm. Las notas largas van con
  `Text(encuadre=False)` para que no manden sobre la escala del dibujo.
- **Balasto con resortes bidireccionales**; la variante de solo compresión se
  implementó y se retiró por decisión del usuario.
- **Solo la punta de la pila lleva restricción** (U3), el fuste solo balasto.
  `reference_project()` lo apaga a propósito para contrastar con el `.s2k`
  original, que sí lleva resorte de punta.
- **Cada pila se analiza y se arma por separado** (`PileZone.piles`,
  `checks["pilas_resumen"]`, `sizing.dimensionar_pilas(por_pila=True)`). En un
  corte de profundidad variable el máximo del grupo no representa a ninguna.
- En SAP, para una viga horizontal el eje local 2 es el vertical: **M3 es la
  flexión vertical y M2 la horizontal**. Cada plano se diseña contra su propia
  orientación de sección.

## Errores propios que ya se pagaron

Están corregidos y fijados con pruebas; no volver a introducirlos.

- El patrón `SOBRECARGA` se generaba y **no entraba en ninguna combinación**.
- La viga cabezal diseñaba sus dos momentos contra la misma orientación.
- El volumen de concreto integraba solo la corona, midiendo desde el datum.
- `Scene.bbox()` no miraba `halign`: un rótulo centrado se medía entero hacia la
  derecha y el encuadre salía mal.
- El DXF se exportaba desde la lámina (milímetros de papel) mientras la cabecera
  declaraba metros: un muro de 9.30 m medía 465.
- `/api/export/excel` recibía solo el proyecto y pasaba `checks=None`: el botón
  de la app bajaba un libro sin resultados mientras el script sacaba uno
  completo. **Cada endpoint que usa la interfaz hay que probarlo por la
  interfaz**; el camino por script no lo cubre.
- Comparar dos DXF por **longitud** no sirve: coincidieron byte a byte en tamaño
  siendo distintos. Comparar contenido.

## Estado y lo que queda abierto

Todo verde y validado contra SAP real. Pendiente o mejorable:

- **Cajetín**: `INGENIERO`, `MATRICULA` y `CLIENTE` van vacíos en
  `proyectos/altos_la_molina.py` a propósito —son datos personales y el repo es
  público—. Se rellenan en la copia local o desde el panel «Proyecto».
- **Escalas**: las secciones de pila podrían subir a 1:10 y el detalle de
  arranque a 1:15 si se les da fila propia; hoy comparten ancho.
- **Caso por etapas**: sigue sin resolverlo SAP (ver arriba).
- Con 12 modos la masa acumulada llega a 0.75 en X: para usar el modal en serio
  hay que subir el número de modos.
- El estudio geotécnico del que salió `proyectos/altos_la_molina.py` **no está
  en el repo** (documento de un tercero). Los datos que hacen falta ya están
  traducidos en ese archivo, con la referencia a la tabla de origen de cada uno.
