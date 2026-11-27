import os #   os        -> manejar rutas de archivos y carpetas
import sys #   sys       -> saber si el programa corre empaquetado (.app / .exe)
import tkinter as tk
from tkinter import ttk, messagebox   #   tkinter   -> ventanas; ttk = widgets con estilo; messagebox = avisos emergentes
import oracledb#   oracledb  -> conexión con la base de datos Oracle

# ============================================================
# PALETA (solo tonos de azul)
# ============================================================
AZUL_MARINO = "#16365f"   # barra lateral, encabezados de tabla
AZUL_HOVER = "#1f4a80"    # barra lateral al pasar el mouse
AZUL = "#2563eb"          # botones y selección
AZUL_OSCURO = "#1d4ed8"   # botón al pasar el mouse
AZUL_CLARO = "#dbeafe"    # botones secundarios, filas alternas
AZUL_PALIDO = "#eff3f9"   # fondo general
AZUL_BORDE = "#c3d4ee"    # bordes
AZUL_TEXTO = "#12315a"    # texto principal
AZUL_GRIS = "#5b7499"     # texto secundario
AZUL_SUAVE = "#9db8e0"    # texto claro sobre azul marino
BLANCO = "#ffffff"

# ============================================================
# CONFIGURACION: lee el archivo .env de la carpeta PROYECTO FINAL
# (copia .env.example como .env y pon tu password real)
# ============================================================


# Devuelve la ruta de un archivo incluido en la app (como Logo.png).
# Empaquetada con PyInstaller usa la carpeta temporal _MEIPASS; si no, la carpeta de este script.
def ruta_recurso(nombre):
    """Archivos incluidos dentro de la app (Logo.png)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nombre)


# Localiza el archivo .env que trae los datos de conexión a la base de datos.
def buscar_env():
    """Busca .env junto a la app (.app / .exe) o en la carpeta del proyecto."""
    # 'frozen' es True cuando corre como app empaquetada (MAPESU.app / .exe)
    if getattr(sys, "frozen", False):
        exe = os.path.dirname(sys.executable)
        # Lugares donde busca el .env cuando está empaquetada
        candidatos = [
            os.path.join(exe, "..", "..", "..", ".env"),  # junto a MAPESU.app (Mac)
            os.path.join(exe, ".env"),                    # junto al .exe (Windows)
        ]
    else:
        # Corriendo desde PyCharm o terminal: el .env está una carpeta arriba de 'interfaz'
        candidatos = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")]
    # Usa el primer archivo que exista; si ninguno existe devuelve el primero (conectar() avisará)
    return next((c for c in candidatos if os.path.exists(c)), candidatos[0])


# Ruta final del .env (se calcula una sola vez al iniciar)
RUTA_ENV = buscar_env()


# Lee el .env y lo convierte en un diccionario {nombre: valor}
def leer_env(ruta):
    datos = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                # Ignora líneas vacías y comentarios (#); separa cada línea en CLAVE=valor
                if linea and not linea.startswith("#") and "=" in linea:
                    k, v = linea.split("=", 1)
                    datos[k.strip()] = v.strip()
    return datos


# Configuración cargada (DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_SERVICE_NAME)
CFG = leer_env(RUTA_ENV)


# Abre una conexión nueva a Oracle con los datos del .env
def conectar():
    # Si no se leyó nada del .env, avisa con un error claro
    if not CFG:
        raise RuntimeError("No se encontró el archivo .env en la carpeta PROYECTO FINAL.\n"
                           "Copia .env.example como .env y pon tu password.")
    # Valores por defecto: localhost y puerto 1521
    host = CFG.get("DB_HOST", "localhost")
    puerto = int(CFG.get("DB_PORT", "1521"))
    # Si el .env trae DB_SID usa SID; si no, usa Service Name (FREEPDB1, XEPDB1...)
    if CFG.get("DB_SID"):
        dsn = oracledb.makedsn(host, puerto, sid=CFG["DB_SID"])
    else:
        dsn = oracledb.makedsn(host, puerto, service_name=CFG.get("DB_SERVICE_NAME", "XEPDB1"))
    # Conecta con el usuario y contraseña del .env
    return oracledb.connect(user=CFG["DB_USER"], password=CFG["DB_PASSWORD"], dsn=dsn)


# Ejecuta un SELECT y devuelve todas las filas.
# Los parámetros (:nombre) evitan la inyección SQL; 'with' cierra la conexión solo.
def consultar(sql, params=None):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or {})
        return cur.fetchall()


# Ejecuta INSERT / UPDATE / DELETE y guarda el cambio con commit.
def ejecutar(sql, params=None):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or {})
        conn.commit()


# Registra una venta completa en UNA sola transacción:
# si algo falla (ej. falta de stock) no se guarda nada.
def registrar_venta(id_empleado, id_cliente, carrito):
    """Guarda cabecera, detalle y descuenta stock en una sola transaccion."""
    with conectar() as conn:
        cur = conn.cursor()
        # Total = suma de cantidad × precio de cada renglón del carrito
        total = sum(i["cantidad"] * i["precio"] for i in carrito)
        # Variable de salida para recibir el ID que Oracle genera para la venta
        out_id = cur.var(int)
        # 1) Crea la cabecera del ticket en VENTAS y obtiene su ID (RETURNING ... INTO)
        cur.execute(
            "INSERT INTO VENTAS (TOTAL, ID_CLIENTE, ID_EMPLEADO) "
            "VALUES (:t, :c, :e) RETURNING ID_VENTA INTO :idv",
            t=total, c=id_cliente, e=id_empleado, idv=out_id)
        # ID de la venta recién creada
        id_venta = out_id.getvalue()[0]
        # 2) Por cada producto del carrito:
        for i in carrito:
            # Descuenta el stock solo si alcanza (STOCK >= cantidad pedida)
            cur.execute(
                "UPDATE PRODUCTOS SET STOCK = STOCK - :q "
                "WHERE ID_PRODUCTO = :p AND STOCK >= :q",
                q=i["cantidad"], p=i["id"])
            # Si no se actualizó ninguna fila no había stock: deshace todo y avisa
            if cur.rowcount == 0:
                conn.rollback()
                raise ValueError(f"Stock insuficiente de {i['nombre']}")
            # Guarda el renglón del ticket en DETALLE_VENTAS
            cur.execute(
                "INSERT INTO DETALLE_VENTAS (ID_VENTA, ID_PRODUCTO, CANTIDAD, "
                "PRECIO_UNITARIO, SUBTOTAL) VALUES (:v, :p, :q, :pr, :s)",
                v=id_venta, p=i["id"], q=i["cantidad"], pr=i["precio"],
                s=i["cantidad"] * i["precio"])
        # 3) Todo salió bien: confirma los cambios
        conn.commit()
        return id_venta, total


# Los combos muestran textos como '22 - Coca-Cola'; esto toma solo el número (22).
def id_de(texto):
    return int(texto.split(" - ")[0])


# Clase principal: la ventana de la aplicación (hereda de tk.Tk).
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # Título y tamaño de la ventana
        self.title("MAPESU - Punto de venta")
        self.geometry("1050x650")
        self.configure(bg=AZUL_PALIDO)
        # Estado de la app: carrito (en memoria), productos cargados y página actual
        self.carrito = []
        self.productos = {}
        self.actual = None

        # Aplica colores y estilos a todos los widgets
        self.aplicar_estilos()

        # ---- barra lateral ----
        self.sidebar = tk.Frame(self, bg=AZUL_MARINO, width=190)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.logo_img = self.cargar_logo()  # guardar referencia o Tk lo borra
        if self.logo_img:
            tk.Label(self.sidebar, image=self.logo_img, bg=AZUL_MARINO,
                     borderwidth=0).pack(pady=(16, 0))
        tk.Label(self.sidebar, text="MAPESU", bg=AZUL_MARINO, fg=BLANCO,
                 font=("Helvetica", 22, "bold")).pack(anchor="w", padx=18, pady=(10, 0))
        tk.Label(self.sidebar, text="GESTIÓN COMERCIAL", bg=AZUL_MARINO, fg=AZUL_SUAVE,
                 font=("Helvetica", 10)).pack(anchor="w", padx=18, pady=(2, 22))

        # ---- area de contenido ----
        self.contenido = tk.Frame(self, bg=AZUL_PALIDO)
        self.contenido.pack(side="left", fill="both", expand=True, padx=18, pady=14)

        # Una página (frame) por cada sección del menú
        self.tab_cat = ttk.Frame(self.contenido)
        self.tab_prod = ttk.Frame(self.contenido)
        self.tab_ven = ttk.Frame(self.contenido)
        self.tab_tic = ttk.Frame(self.contenido)
        # Diccionario nombre -> página, para mostrarlas con mostrar()
        self.paginas = {"Catálogos": self.tab_cat,
                        "Productos": self.tab_prod,
                        "Ventas": self.tab_ven,
                        "Tickets": self.tab_tic}
        # Crea un botón del menú lateral por cada página
        self.nav = {}
        for nombre in self.paginas:
            self.crear_item_menu(nombre)

        # Título y subtítulo de cada página
        self.encabezado(self.tab_cat, "Catálogos", "Categorías, empleados, clientes y proveedores")
        self.encabezado(self.tab_prod, "Productos", "Inventario disponible")
        self.encabezado(self.tab_ven, "Ventas", "Registro de ventas y ticket")

        # Construye el contenido de cada página
        self.armar_catalogos()
        self.armar_productos()
        self.encabezado(self.tab_tic, "Tickets", "Historial de ventas realizadas")
        self.armar_ventas()
        self.armar_tickets()
        # Lee la base de datos y llena todas las tablas y listas
        self.refrescar()
        # Página con la que inicia la app
        self.mostrar("Ventas")

    # ---------------- ESTILO Y NAVEGACION ----------------
    # Define colores, fuentes y apariencia de los widgets ttk (tema 'clam').
    def aplicar_estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")  # 'clam' respeta los colores en macOS
        s.configure(".", background=AZUL_PALIDO, foreground=AZUL_TEXTO,
                    font=("Helvetica", 12), bordercolor=AZUL_BORDE,
                    lightcolor=AZUL_PALIDO, darkcolor=AZUL_PALIDO)
        s.configure("TFrame", background=AZUL_PALIDO)
        s.configure("TLabel", background=BLANCO, foreground=AZUL_TEXTO)
        s.configure("Titulo.TLabel", background=AZUL_PALIDO, foreground=AZUL_MARINO,
                    font=("Helvetica", 22, "bold"))
        s.configure("Sub.TLabel", background=AZUL_PALIDO, foreground=AZUL_GRIS,
                    font=("Helvetica", 12))
        s.configure("Total.TLabel", background=AZUL_PALIDO, foreground=AZUL_OSCURO,
                    font=("Helvetica", 18, "bold"))

        # Marcos con borde (LabelFrame)
        s.configure("TLabelframe", background=BLANCO, bordercolor=AZUL_BORDE,
                    lightcolor=BLANCO, darkcolor=BLANCO, borderwidth=1, relief="solid")
        s.configure("TLabelframe.Label", background=BLANCO, foreground=AZUL_OSCURO,
                    font=("Helvetica", 12, "bold"))

        # Botones: azul por defecto; 'Sec.TButton' es el secundario (azul claro)
        s.configure("TButton", background=AZUL, foreground=BLANCO, borderwidth=0,
                    focusthickness=0, padding=(14, 7), font=("Helvetica", 12, "bold"))
        s.map("TButton", background=[("pressed", AZUL_MARINO), ("active", AZUL_OSCURO)])
        s.configure("Sec.TButton", background=AZUL_CLARO, foreground=AZUL_MARINO)
        s.map("Sec.TButton", background=[("pressed", AZUL_BORDE), ("active", AZUL_BORDE)])

        # pestañas (Notebook) en azul
        s.configure("TNotebook", background=AZUL_PALIDO, borderwidth=0)
        s.configure("TNotebook.Tab", background=AZUL_CLARO, foreground=AZUL_MARINO,
                    padding=(14, 6), font=("Helvetica", 12, "bold"))
        s.map("TNotebook.Tab", background=[("selected", AZUL)],
              foreground=[("selected", BLANCO)])

        # Campos de texto, listas desplegables y spinbox
        for w in ("TEntry", "TCombobox", "TSpinbox"):
            s.configure(w, fieldbackground=BLANCO, background=AZUL_CLARO,
                        foreground=AZUL_TEXTO, bordercolor=AZUL_BORDE,
                        lightcolor=AZUL_BORDE, darkcolor=AZUL_BORDE,
                        arrowcolor=AZUL_OSCURO, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", BLANCO)],
              foreground=[("readonly", AZUL_TEXTO)],
              selectbackground=[("readonly", BLANCO)],
              selectforeground=[("readonly", AZUL_TEXTO)])
        # Colores de la lista que se despliega en los combobox
        self.option_add("*TCombobox*Listbox.background", BLANCO)
        self.option_add("*TCombobox*Listbox.foreground", AZUL_TEXTO)
        self.option_add("*TCombobox*Listbox.selectBackground", AZUL)
        self.option_add("*TCombobox*Listbox.selectForeground", BLANCO)

        # Tablas (Treeview): filas, selección y encabezados
        s.configure("Treeview", background=BLANCO, fieldbackground=BLANCO,
                    foreground=AZUL_TEXTO, rowheight=28, bordercolor=AZUL_BORDE,
                    borderwidth=1, font=("Helvetica", 12))
        s.map("Treeview", background=[("selected", AZUL)],
              foreground=[("selected", BLANCO)])
        s.configure("Treeview.Heading", background=AZUL_MARINO, foreground=BLANCO,
                    relief="flat", padding=6, font=("Helvetica", 12, "bold"))
        s.map("Treeview.Heading", background=[("active", AZUL_HOVER)])

    def cargar_logo(self):
        """Carga Logo.png (misma carpeta que este archivo). Si no existe, no muestra logo."""
        ruta = ruta_recurso("Logo.png")
        try:
            return tk.PhotoImage(file=ruta)
        except tk.TclError:
            return None

    # Pone título y subtítulo en la parte de arriba de una página
    def encabezado(self, frame, titulo, subtitulo):
        ttk.Label(frame, text=titulo, style="Titulo.TLabel").pack(anchor="w", pady=(0, 0))
        ttk.Label(frame, text=subtitulo, style="Sub.TLabel").pack(anchor="w", pady=(0, 10))

    # Crea un botón del menú lateral con efecto al pasar el mouse.
    def crear_item_menu(self, nombre):
        lbl = tk.Label(self.sidebar, text="  " + nombre, bg=AZUL_MARINO, fg=BLANCO,
                       font=("Helvetica", 14), anchor="w", padx=12, pady=10, cursor="hand2")
        lbl.pack(fill="x")
        # Clic -> muestra esa página
        lbl.bind("<Button-1>", lambda e, n=nombre: self.mostrar(n))
        # Mouse encima / fuera -> cambia el color (la página activa queda resaltada)
        lbl.bind("<Enter>", lambda e, n=nombre: self.nav[n].config(
            bg=AZUL if n == self.actual else AZUL_HOVER))
        lbl.bind("<Leave>", lambda e, n=nombre: self.nav[n].config(
            bg=AZUL if n == self.actual else AZUL_MARINO))
        self.nav[nombre] = lbl

    # Muestra la página elegida: oculta las demás y resalta su botón del menú.
    def mostrar(self, nombre):
        self.actual = nombre
        for n, frame in self.paginas.items():
            frame.pack_forget()
            self.nav[n].config(bg=AZUL if n == nombre else AZUL_MARINO)
        self.paginas[nombre].pack(fill="both", expand=True)

    # ---------------- UTILIDADES EDITAR / ELIMINAR ----------------
    # Devuelve el ID de la fila seleccionada en una tabla (o avisa si no hay ninguna).
    def sel_id(self, tv):
        """Devuelve el ID de la fila seleccionada (el iid de cada fila es su ID en la BD)."""
        sel = tv.selection()
        if not sel:
            messagebox.showwarning("Selecciona", "Primero selecciona una fila de la tabla")
            return None
        return int(sel[0])

    # Ventana emergente genérica para editar datos.
    # Recibe los campos y una función 'guardar' que se ejecuta al presionar Guardar.
    def dialogo(self, titulo, campos, guardar):
        """Ventana de edición. campos: [(etiqueta, valor_inicial, lista_opciones_o_None)]"""
        win = tk.Toplevel(self)
        win.title(titulo)
        win.configure(bg=AZUL_PALIDO)
        win.transient(self)
        win.resizable(False, False)
        widgets = []
        # Crea una etiqueta y un campo por cada dato; si trae opciones, usa lista desplegable
        for r, (etiqueta, valor, opciones) in enumerate(campos):
            ttk.Label(win, text=etiqueta + ":", style="Sub.TLabel").grid(
                row=r, column=0, padx=12, pady=6, sticky="e")
            if opciones is not None:
                w = ttk.Combobox(win, state="readonly", values=opciones, width=30)
                w.set(valor)
            else:
                w = ttk.Entry(win, width=32)
                w.insert(0, valor)
            w.grid(row=r, column=1, padx=12, pady=6)
            widgets.append(w)

        # Al guardar: valida, guarda, cierra la ventana y refresca las tablas
        def aceptar():
            try:
                guardar([w.get().strip() for w in widgets])
            # ValueError = dato inválido (nombre vacío, precio que no es número...)
            except ValueError:
                return messagebox.showwarning("Datos inválidos", "Revisa los datos capturados",
                                              parent=win)
            except Exception as e:
                return messagebox.showerror("Error", str(e), parent=win)
            win.destroy()
            self.refrescar()

        # Botones Guardar / Cancelar
        bar = ttk.Frame(win)
        bar.grid(row=len(campos), column=0, columnspan=2, pady=12)
        ttk.Button(bar, text="Guardar", command=aceptar).pack(side="left", padx=5)
        ttk.Button(bar, text="Cancelar", style="Sec.TButton",
                   command=win.destroy).pack(side="left", padx=5)
        # Modal: bloquea la ventana principal hasta cerrar esta
        win.grab_set()

    # Baja lógica genérica (empleados, clientes, proveedores y productos).
    def baja(self, tv, tabla, col_id, texto):
        """'Elimina' poniendo ACTIVO = 0 (así se conserva el historial de ventas)."""
        i = self.sel_id(tv)
        if i is None:
            return
        # Pide confirmación antes de dar de baja
        if not messagebox.askyesno("Confirmar",
                                   f"¿Eliminar {texto}?\n(Las ventas anteriores se conservan)"):
            return
        try:
            # Tabla y columna vienen del código (no del usuario); el ID va como parámetro
            ejecutar(f"UPDATE {tabla} SET ACTIVO = 0 WHERE {col_id} = :i", {"i": i})
            self.refrescar()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------------- CATALOGOS ----------------
    # Crea una pestaña de catálogo: formulario 'Nuevo', tabla y botones Editar / Eliminar.
    # Devuelve (formulario, tabla) para que cada catálogo agregue sus campos.
    def pestana(self, nb, titulo, cols, anchos, editar, eliminar):
        fr = ttk.Frame(nb)
        nb.add(fr, text=f"  {titulo}  ")
        form = ttk.LabelFrame(fr, text="Nuevo")
        form.pack(fill="x", padx=10, pady=10)
        tv = ttk.Treeview(fr, columns=cols, show="headings", height=9)
        for c, w in zip(cols, anchos):
            tv.heading(c, text=c.capitalize())
            tv.column(c, width=w)
        tv.pack(fill="both", expand=True, padx=10)
        bar = ttk.Frame(fr)
        bar.pack(fill="x", padx=10, pady=10)
        ttk.Button(bar, text="Editar seleccionado",
                   command=lambda: editar(tv)).pack(side="left")
        ttk.Button(bar, text="Eliminar seleccionado", style="Sec.TButton",
                   command=lambda: eliminar(tv)).pack(side="left", padx=6)
        return form, tv

    # Arma la página Catálogos con cuatro pestañas.
    def armar_catalogos(self):
        nb = ttk.Notebook(self.tab_cat)
        nb.pack(fill="both", expand=True)

        # Pestaña Categorías: campo Nombre + botón Agregar
        f, self.tv_cat = self.pestana(nb, "Categorías", ("id", "nombre", "descripcion"),
                                      (60, 220, 320), self.edit_categoria, self.del_categoria)
        self.cat_nombre = ttk.Entry(f, width=30)
        ttk.Label(f, text="Nombre:").grid(row=0, column=0, padx=5, pady=5)
        self.cat_nombre.grid(row=0, column=1, padx=5)
        ttk.Button(f, text="Agregar", command=self.add_categoria).grid(row=0, column=2, padx=5)

        # Pestaña Empleados (puesto por defecto: CAJERO)
        f, self.tv_emp = self.pestana(nb, "Empleados", ("id", "nombre", "puesto", "telefono"),
                                      (60, 220, 140, 140), self.edit_empleado, self.del_empleado)
        self.emp_nombre = ttk.Entry(f, width=30)
        self.emp_puesto = ttk.Entry(f, width=15)
        self.emp_puesto.insert(0, "CAJERO")
        ttk.Label(f, text="Nombre:").grid(row=0, column=0, padx=5, pady=5)
        self.emp_nombre.grid(row=0, column=1, padx=5)
        ttk.Label(f, text="Puesto:").grid(row=0, column=2, padx=5)
        self.emp_puesto.grid(row=0, column=3, padx=5)
        ttk.Button(f, text="Agregar", command=self.add_empleado).grid(row=0, column=4, padx=5)

        # Pestaña Clientes
        f, self.tv_cli = self.pestana(nb, "Clientes", ("id", "nombre", "telefono", "direccion"),
                                      (60, 220, 130, 250), self.edit_cliente, self.del_cliente)
        self.cli_nombre = ttk.Entry(f, width=30)
        self.cli_tel = ttk.Entry(f, width=15)
        ttk.Label(f, text="Nombre:").grid(row=0, column=0, padx=5, pady=5)
        self.cli_nombre.grid(row=0, column=1, padx=5)
        ttk.Label(f, text="Teléfono:").grid(row=0, column=2, padx=5)
        self.cli_tel.grid(row=0, column=3, padx=5)
        ttk.Button(f, text="Agregar", command=self.add_cliente).grid(row=0, column=4, padx=5)

        # Pestaña Proveedores
        f, self.tv_prov = self.pestana(nb, "Proveedores",
                                       ("id", "nombre", "telefono", "correo", "direccion"),
                                       (60, 200, 120, 200, 220),
                                       self.edit_proveedor, self.del_proveedor)
        self.prov_nombre = ttk.Entry(f, width=30)
        self.prov_tel = ttk.Entry(f, width=15)
        ttk.Label(f, text="Nombre:").grid(row=0, column=0, padx=5, pady=5)
        self.prov_nombre.grid(row=0, column=1, padx=5)
        ttk.Label(f, text="Teléfono:").grid(row=0, column=2, padx=5)
        self.prov_tel.grid(row=0, column=3, padx=5)
        ttk.Button(f, text="Agregar", command=self.add_proveedor).grid(row=0, column=4, padx=5)

    # --- categorías ---
    # Agrega una categoría (INSERT) validando que el nombre no esté vacío.
    def add_categoria(self):
        n = self.cat_nombre.get().strip()
        if not n:
            return messagebox.showwarning("Falta dato", "Escribe el nombre")
        try:
            ejecutar("INSERT INTO CATEGORIAS (NOMBRE) VALUES (:n)", {"n": n})
            self.cat_nombre.delete(0, "end")
            self.refrescar()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Edita una categoría: lee los datos actuales, abre el diálogo y hace UPDATE.
    def edit_categoria(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        # Datos actuales de la fila seleccionada
        n, d = consultar("SELECT NOMBRE, DESCRIPCION FROM CATEGORIAS "
                         "WHERE ID_CATEGORIA = :i", {"i": i})[0]

        # Se ejecuta al presionar Guardar; 'or None' guarda NULL si el campo queda vacío
        def guardar(v):
            if not v[0]:
                raise ValueError
            ejecutar("UPDATE CATEGORIAS SET NOMBRE = :n, DESCRIPCION = :d "
                     "WHERE ID_CATEGORIA = :i", {"n": v[0], "d": v[1] or None, "i": i})
        self.dialogo("Editar categoría",
                     [("Nombre", n, None), ("Descripción", d or "", None)], guardar)

    # Elimina la categoría de verdad (DELETE), no es baja lógica.
    def del_categoria(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        if not messagebox.askyesno("Confirmar", "¿Eliminar la categoría?"):
            return
        try:
            ejecutar("DELETE FROM CATEGORIAS WHERE ID_CATEGORIA = :i", {"i": i})
            self.refrescar()
        # Oracle rechaza el borrado si hay productos usando la categoría (llave foránea)
        except oracledb.IntegrityError:
            messagebox.showwarning("No se puede eliminar",
                                   "La categoría tiene productos.\n"
                                   "Cambia esos productos de categoría primero.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # --- empleados ---
    # Agrega un empleado; si el puesto queda vacío usa CAJERO.
    def add_empleado(self):
        n = self.emp_nombre.get().strip()
        if not n:
            return messagebox.showwarning("Falta dato", "Escribe el nombre")
        try:
            ejecutar("INSERT INTO EMPLEADOS (NOMBRE, PUESTO) VALUES (:n, :p)",
                     {"n": n, "p": self.emp_puesto.get().strip() or "CAJERO"})
            self.emp_nombre.delete(0, "end")
            self.refrescar()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Edita nombre, puesto y teléfono del empleado.
    def edit_empleado(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        n, p, t = consultar("SELECT NOMBRE, PUESTO, TELEFONO FROM EMPLEADOS "
                            "WHERE ID_EMPLEADO = :i", {"i": i})[0]

        def guardar(v):
            if not v[0]:
                raise ValueError
            ejecutar("UPDATE EMPLEADOS SET NOMBRE = :n, PUESTO = :p, TELEFONO = :t "
                     "WHERE ID_EMPLEADO = :i",
                     {"n": v[0], "p": v[1] or "CAJERO", "t": v[2] or None, "i": i})
        self.dialogo("Editar empleado", [("Nombre", n, None), ("Puesto", p, None),
                                         ("Teléfono", t or "", None)], guardar)

    # Baja lógica: ACTIVO = 0
    def del_empleado(self, tv):
        self.baja(tv, "EMPLEADOS", "ID_EMPLEADO", "este empleado")

    # --- clientes ---
    # Agrega un cliente (nombre y teléfono).
    def add_cliente(self):
        n = self.cli_nombre.get().strip()
        if not n:
            return messagebox.showwarning("Falta dato", "Escribe el nombre")
        try:
            ejecutar("INSERT INTO CLIENTES (NOMBRE, TELEFONO) VALUES (:n, :t)",
                     {"n": n, "t": self.cli_tel.get().strip() or None})
            self.cli_nombre.delete(0, "end")
            self.cli_tel.delete(0, "end")
            self.refrescar()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Edita nombre, teléfono y dirección del cliente.
    def edit_cliente(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        n, t, d = consultar("SELECT NOMBRE, TELEFONO, DIRECCION FROM CLIENTES "
                            "WHERE ID_CLIENTE = :i", {"i": i})[0]

        def guardar(v):
            if not v[0]:
                raise ValueError
            ejecutar("UPDATE CLIENTES SET NOMBRE = :n, TELEFONO = :t, DIRECCION = :d "
                     "WHERE ID_CLIENTE = :i",
                     {"n": v[0], "t": v[1] or None, "d": v[2] or None, "i": i})
        self.dialogo("Editar cliente", [("Nombre", n, None), ("Teléfono", t or "", None),
                                        ("Dirección", d or "", None)], guardar)

    # Baja lógica: ACTIVO = 0
    def del_cliente(self, tv):
        self.baja(tv, "CLIENTES", "ID_CLIENTE", "este cliente")

    # --- proveedores ---
    # Agrega un proveedor (nombre y teléfono).
    def add_proveedor(self):
        n = self.prov_nombre.get().strip()
        if not n:
            return messagebox.showwarning("Falta dato", "Escribe el nombre del proveedor")
        try:
            ejecutar("INSERT INTO PROVEEDORES (NOMBRE, TELEFONO) VALUES (:n, :t)",
                     {"n": n, "t": self.prov_tel.get().strip() or None})
            self.prov_nombre.delete(0, "end")
            self.prov_tel.delete(0, "end")
            self.refrescar()
        # El nombre del proveedor es UNIQUE: si ya existe, avisa
        except oracledb.IntegrityError:
            messagebox.showwarning("Duplicado", "Ya existe un proveedor con ese nombre")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Edita nombre, teléfono, correo y dirección del proveedor.
    def edit_proveedor(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        n, t, c, d = consultar("SELECT NOMBRE, TELEFONO, CORREO, DIRECCION FROM PROVEEDORES "
                               "WHERE ID_PROVEEDOR = :i", {"i": i})[0]

        def guardar(v):
            if not v[0]:
                raise ValueError
            ejecutar("UPDATE PROVEEDORES SET NOMBRE = :n, TELEFONO = :t, CORREO = :c, "
                     "DIRECCION = :d WHERE ID_PROVEEDOR = :i",
                     {"n": v[0], "t": v[1] or None, "c": v[2] or None, "d": v[3] or None, "i": i})
        self.dialogo("Editar proveedor", [("Nombre", n, None), ("Teléfono", t or "", None),
                                          ("Correo", c or "", None),
                                          ("Dirección", d or "", None)], guardar)

    # Baja lógica, pero primero revisa que no surta productos activos.
    def del_proveedor(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        # Cuenta los productos activos de este proveedor
        n = consultar("SELECT COUNT(*) FROM PRODUCTOS WHERE ID_PROVEEDOR = :i AND ACTIVO = 1",
                      {"i": i})[0][0]
        if n:
            return messagebox.showwarning("No se puede eliminar",
                                          f"Este proveedor surte {n} producto(s) activo(s).\n"
                                          "Cambia el proveedor de esos productos primero.")
        self.baja(tv, "PROVEEDORES", "ID_PROVEEDOR", "este proveedor")

    # ---------------- PRODUCTOS ----------------
    # Arma la página Productos: formulario de alta, tabla y botones Editar / Eliminar.
    def armar_productos(self):
        f = self.tab_prod
        form = ttk.LabelFrame(f, text="Nuevo producto")
        form.pack(fill="x", padx=10, pady=10)
        self.p_nombre = ttk.Entry(form, width=25)
        self.p_precio = ttk.Entry(form, width=10)
        self.p_stock = ttk.Entry(form, width=8)
        self.p_cat = ttk.Combobox(form, state="readonly", width=22)
        self.p_prov = ttk.Combobox(form, state="readonly", width=22)
        for i, (t, w) in enumerate([("Nombre", self.p_nombre), ("Precio", self.p_precio),
                                    ("Stock", self.p_stock)]):
            ttk.Label(form, text=t + ":").grid(row=0, column=i * 2, padx=4, pady=5)
            w.grid(row=0, column=i * 2 + 1, padx=4)
        ttk.Label(form, text="Categoría:").grid(row=1, column=0, padx=4, pady=5)
        self.p_cat.grid(row=1, column=1, padx=4)
        ttk.Label(form, text="Proveedor:").grid(row=1, column=2, padx=4)
        self.p_prov.grid(row=1, column=3, padx=4)
        ttk.Button(form, text="Agregar", command=self.add_producto).grid(row=1, column=5, padx=6)

        # Tabla de productos
        cols = ("id", "nombre", "precio", "stock", "categoria", "proveedor")
        self.tv_prod = ttk.Treeview(f, columns=cols, show="headings", height=11)
        for c, w in zip(cols, (50, 220, 80, 70, 150, 170)):
            self.tv_prod.heading(c, text=c.capitalize())
            self.tv_prod.column(c, width=w)
        self.tv_prod.pack(fill="both", expand=True, padx=10, pady=5)

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=10, pady=10)
        ttk.Button(bar, text="Editar seleccionado",
                   command=lambda: self.edit_producto(self.tv_prod)).pack(side="left")
        ttk.Button(bar, text="Eliminar seleccionado", style="Sec.TButton",
                   command=lambda: self.del_producto(self.tv_prod)).pack(side="left", padx=6)

    # Agrega un producto validando precio, stock, categoría y proveedor.
    def add_producto(self):
        try:
            nombre = self.p_nombre.get().strip()
            # float() e int() lanzan ValueError si el texto no es un número
            precio = float(self.p_precio.get())
            stock = int(self.p_stock.get() or 0)
            # Todo producto necesita proveedor (NOT NULL en la base de datos)
            if not self.p_prov.get():
                return messagebox.showwarning(
                    "Falta proveedor",
                    "Elige un proveedor.\nSi no existe, primero dalo de alta en "
                    "Catálogos > Proveedores.")
            cat = id_de(self.p_cat.get())
            prov = id_de(self.p_prov.get())
            if not nombre:
                raise ValueError("Escribe el nombre")
            # INSERT del producto
            ejecutar("INSERT INTO PRODUCTOS (NOMBRE, PRECIO_VENTA, STOCK, ID_CATEGORIA, ID_PROVEEDOR) "
                     "VALUES (:n, :p, :s, :c, :pv)",
                     {"n": nombre, "p": precio, "s": stock, "c": cat, "pv": prov})
            # Limpia el formulario
            for w in (self.p_nombre, self.p_precio, self.p_stock):
                w.delete(0, "end")
            self.p_prov.set("")
            self.refrescar()
        except ValueError:
            messagebox.showwarning("Datos inválidos", "Revisa nombre, precio, stock, categoría y proveedor")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Edita un producto: carga los valores actuales y las listas de categorías y proveedores.
    def edit_producto(self, tv):
        i = self.sel_id(tv)
        if i is None:
            return
        n, pr, s, c, pv = consultar("SELECT NOMBRE, PRECIO_VENTA, STOCK, ID_CATEGORIA, ID_PROVEEDOR "
                                    "FROM PRODUCTOS WHERE ID_PRODUCTO = :i", {"i": i})[0]
        # Busca en las listas la opción que corresponde a la categoría y proveedor actuales
        cats = list(self.p_cat["values"])
        actual = next((x for x in cats if x.startswith(f"{c} - ")), "")
        provs = list(self.p_prov["values"])
        actual_pv = next((x for x in provs if x.startswith(f"{pv} - ")), "")

        # Se ejecuta al presionar Guardar: actualiza el producto
        def guardar(v):
            if not v[0]:
                raise ValueError
            ejecutar("UPDATE PRODUCTOS SET NOMBRE = :n, PRECIO_VENTA = :p, STOCK = :s, "
                     "ID_CATEGORIA = :c, ID_PROVEEDOR = :pv WHERE ID_PRODUCTO = :i",
                     {"n": v[0], "p": float(v[1]), "s": int(v[2]), "c": id_de(v[3]),
                      "pv": id_de(v[4]), "i": i})
        self.dialogo("Editar producto",
                     [("Nombre", n, None), ("Precio", f"{float(pr):.2f}", None),
                      ("Stock", str(s), None), ("Categoría", actual, cats),
                      ("Proveedor", actual_pv, provs)], guardar)

    # Baja lógica: ACTIVO = 0
    def del_producto(self, tv):
        self.baja(tv, "PRODUCTOS", "ID_PRODUCTO", "este producto")

    # ---------------- VENTAS ----------------
    # Arma la página Ventas: empleado, cliente, producto, carrito y total.
    def armar_ventas(self):
        f = self.tab_ven
        top = ttk.LabelFrame(f, text="Venta")
        top.pack(fill="x", padx=10, pady=10)
        # Listas desplegables (solo lectura) y cantidad
        self.v_emp = ttk.Combobox(top, state="readonly", width=20)
        self.v_cli = ttk.Combobox(top, state="readonly", width=20)
        self.v_prod = ttk.Combobox(top, state="readonly", width=30)
        self.v_cant = ttk.Spinbox(top, from_=1, to=999, width=5)
        self.v_cant.set(1)
        ttk.Label(top, text="Empleado:").grid(row=0, column=0, padx=4, pady=4)
        self.v_emp.grid(row=0, column=1)
        ttk.Label(top, text="Cliente:").grid(row=0, column=2, padx=4)
        self.v_cli.grid(row=0, column=3)
        ttk.Label(top, text="Producto:").grid(row=1, column=0, padx=4, pady=4)
        self.v_prod.grid(row=1, column=1)
        ttk.Label(top, text="Cantidad:").grid(row=1, column=2, padx=4)
        self.v_cant.grid(row=1, column=3, sticky="w")
        ttk.Button(top, text="Agregar al carrito", command=self.add_carrito).grid(row=1, column=4, padx=8)

        # Tabla del carrito
        cols = ("producto", "cantidad", "precio", "subtotal")
        self.tv_car = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (300, 90, 100, 110)):
            self.tv_car.heading(c, text=c.capitalize())
            self.tv_car.column(c, width=w)
        self.tv_car.pack(fill="both", expand=True, padx=10)

        # Parte inferior: total y botones
        bot = ttk.Frame(f)
        bot.pack(fill="x", padx=10, pady=10)
        self.lbl_total = ttk.Label(bot, text="Total: $0.00", style="Total.TLabel")
        self.lbl_total.pack(side="left")
        ttk.Button(bot, text="Vaciar", style="Sec.TButton", command=self.vaciar).pack(side="right", padx=5)
        ttk.Button(bot, text="Registrar venta", command=self.cobrar).pack(side="right")

    # Agrega el producto elegido al carrito (en memoria; aún no se guarda en la base).
    def add_carrito(self):
        try:
            texto = self.v_prod.get()
            if not texto:
                raise ValueError
            cant = int(self.v_cant.get())
            pid = id_de(texto)
            # Datos del producto: nombre, precio y stock
            nombre, precio, stock = self.productos[pid]
            # Cantidad de ese producto que ya está en el carrito
            en_carrito = sum(i["cantidad"] for i in self.carrito if i["id"] == pid)
            # No permite pasar del stock disponible
            if cant <= 0 or cant + en_carrito > stock:
                return messagebox.showwarning("Stock", f"Solo hay {stock} en existencia")
            # Agrega el renglón al carrito
            self.carrito.append({"id": pid, "nombre": nombre, "cantidad": cant, "precio": precio})
            self.pintar_carrito()
        except (ValueError, KeyError):
            messagebox.showwarning("Datos inválidos", "Elige producto y cantidad válida")

    # Redibuja la tabla del carrito y actualiza el total.
    def pintar_carrito(self):
        self.tv_car.delete(*self.tv_car.get_children())
        total = 0
        for i in self.carrito:
            sub = i["cantidad"] * i["precio"]
            total += sub
            self.tv_car.insert("", "end", values=(i["nombre"], i["cantidad"],
                                                  f"{i['precio']:.2f}", f"{sub:.2f}"))
        self.lbl_total.config(text=f"Total: ${total:.2f}")

    # Vacía el carrito.
    def vaciar(self):
        self.carrito.clear()
        self.pintar_carrito()

    # Registra la venta: valida, guarda en la base y muestra el número de ticket.
    def cobrar(self):
        # Si no pulsaste "Agregar al carrito" pero ya elegiste un producto, se agrega solo
        if not self.carrito and self.v_prod.get():
            self.add_carrito()
        if not self.carrito:
            return messagebox.showwarning("Carrito vacío", "Agrega productos")
        if not self.v_emp.get():
            return messagebox.showwarning("Falta empleado", "Elige quién atiende")
        # 'Público general' = venta sin cliente (se guarda como NULL)
        cli = self.v_cli.get()
        id_cli = None if cli in ("", "0 - Público general") else id_de(cli)
        # Guarda la venta; si falla (ej. sin stock) muestra el error y no guarda nada
        try:
            idv, total = registrar_venta(id_de(self.v_emp.get()), id_cli, self.carrito)
            messagebox.showinfo("Venta registrada", f"Ticket #{idv}\nTotal: ${total:.2f}")
            self.vaciar()
            self.refrescar()
        except Exception as e:
            messagebox.showerror("No se pudo registrar", str(e))

    # ---------------- TICKETS (HISTORIAL) ----------------
    # Arma la página Tickets: lista de ventas y, abajo, el detalle del ticket elegido.
    def armar_tickets(self):
        f = self.tab_tic
        cols = ("ticket", "fecha", "cliente", "empleado", "total")
        self.tv_tic = ttk.Treeview(f, columns=cols, show="headings", height=9)
        for c, w in zip(cols, (70, 150, 200, 200, 100)):
            self.tv_tic.heading(c, text=c.capitalize())
            self.tv_tic.column(c, width=w)
        self.tv_tic.pack(fill="both", expand=True, padx=10, pady=(0, 5))
        # Al seleccionar un ticket se muestra su detalle
        self.tv_tic.bind("<<TreeviewSelect>>", self.mostrar_detalle)

        det = ttk.LabelFrame(f, text="Detalle del ticket seleccionado")
        det.pack(fill="both", expand=True, padx=10, pady=10)
        cols = ("producto", "cantidad", "precio", "subtotal")
        self.tv_det = ttk.Treeview(det, columns=cols, show="headings", height=5)
        for c, w in zip(cols, (300, 90, 100, 110)):
            self.tv_det.heading(c, text=c.capitalize())
            self.tv_det.column(c, width=w)
        self.tv_det.pack(fill="both", expand=True, padx=8, pady=8)

    # Consulta y muestra los productos del ticket seleccionado.
    def mostrar_detalle(self, _evento=None):
        sel = self.tv_tic.selection()
        self.tv_det.delete(*self.tv_det.get_children())
        if not sel:
            return
        try:
            # JOIN con PRODUCTOS para mostrar el nombre en vez del ID
            filas = consultar(
                "SELECT P.NOMBRE, D.CANTIDAD, D.PRECIO_UNITARIO, D.SUBTOTAL "
                "FROM DETALLE_VENTAS D JOIN PRODUCTOS P ON P.ID_PRODUCTO = D.ID_PRODUCTO "
                "WHERE D.ID_VENTA = :v ORDER BY D.ID_DETALLE", {"v": int(sel[0])})
        except Exception as e:
            return messagebox.showerror("Error", str(e))
        for n, q, pr, sub in filas:
            self.tv_det.insert("", "end", values=(n, q, f"{float(pr):.2f}", f"{float(sub):.2f}"))

    # ---------------- REFRESCAR ----------------
    # Vuelve a leer la base y actualiza TODAS las tablas y listas.
    # Se llama después de cada alta, edición, baja o venta.
    def refrescar(self):
        try:
            # Solo trae registros ACTIVO = 1 (los dados de baja no se muestran)
            cats = consultar("SELECT ID_CATEGORIA, NOMBRE, DESCRIPCION FROM CATEGORIAS ORDER BY NOMBRE")
            emps = consultar("SELECT ID_EMPLEADO, NOMBRE, PUESTO, TELEFONO FROM EMPLEADOS "
                             "WHERE ACTIVO = 1 ORDER BY NOMBRE")
            clis = consultar("SELECT ID_CLIENTE, NOMBRE, TELEFONO, DIRECCION FROM CLIENTES "
                             "WHERE ACTIVO = 1 ORDER BY NOMBRE")
            provs = consultar("SELECT ID_PROVEEDOR, NOMBRE, TELEFONO, CORREO, DIRECCION FROM PROVEEDORES "
                              "WHERE ACTIVO = 1 ORDER BY NOMBRE")
            prods = consultar(
                "SELECT P.ID_PRODUCTO, P.NOMBRE, P.PRECIO_VENTA, P.STOCK, C.NOMBRE, PV.NOMBRE "
                "FROM PRODUCTOS P JOIN CATEGORIAS C ON C.ID_CATEGORIA = P.ID_CATEGORIA "
                "JOIN PROVEEDORES PV ON PV.ID_PROVEEDOR = P.ID_PROVEEDOR "
                "WHERE P.ACTIVO = 1 ORDER BY P.NOMBRE")
            # Últimos 200 tickets, el más reciente primero; LEFT JOIN porque el cliente puede ser NULL
            tics = consultar(
                "SELECT V.ID_VENTA, TO_CHAR(V.FECHA_HORA, 'DD/MM/YYYY HH24:MI'), "
                "NVL(C.NOMBRE, 'Público general'), E.NOMBRE, V.TOTAL "
                "FROM VENTAS V JOIN EMPLEADOS E ON E.ID_EMPLEADO = V.ID_EMPLEADO "
                "LEFT JOIN CLIENTES C ON C.ID_CLIENTE = V.ID_CLIENTE "
                "ORDER BY V.ID_VENTA DESC FETCH FIRST 200 ROWS ONLY")
        # Si falla (ej. Oracle apagado) muestra 'Error de conexión'
        except Exception as e:
            return messagebox.showerror("Error de conexión", str(e))

        # Llena las listas desplegables con formato 'ID - Nombre'
        self.p_cat["values"] = [f"{c[0]} - {c[1]}" for c in cats]
        self.v_emp["values"] = [f"{e[0]} - {e[1]}" for e in emps]
        self.v_cli["values"] = ["0 - Público general"] + [f"{c[0]} - {c[1]}" for c in clis]
        self.p_prov["values"] = [f"{c[0]} - {c[1]}" for c in provs]
        # Diccionario de productos {id: (nombre, precio, stock)} que usa el carrito
        self.productos = {i: (n, float(p), s) for i, n, p, s, *_ in prods}
        self.v_prod["values"] = [f"{i} - {n} (${float(p):.2f}, stock {s})" for i, n, p, s, *_ in prods]

        # Auxiliar: borra la tabla y la llena con las filas (el ID de la BD queda como iid)
        def llenar(tv, filas):
            tv.delete(*tv.get_children())
            for fila in filas:
                tv.insert("", "end", iid=str(fila[0]),
                          values=["" if x is None else x for x in fila])

        # Llena cada tabla de la interfaz
        llenar(self.tv_cat, cats)
        llenar(self.tv_emp, emps)
        llenar(self.tv_cli, clis)
        llenar(self.tv_prov, provs)
        llenar(self.tv_prod, [(i, n, f"{float(p):.2f}", s, c, pv) for i, n, p, s, c, pv in prods])
        llenar(self.tv_tic, [(i, f, c, e, f"${float(t):.2f}") for i, f, c, e, t in tics])
        # Limpia el detalle de tickets
        self.tv_det.delete(*self.tv_det.get_children())


# Punto de entrada: crea la ventana y arranca la interfaz
# (solo si se ejecuta este archivo directamente)
if __name__ == "__main__":
    App().mainloop()