# Sistema de Gestión — Repuestos Guevara

Aplicación privada de gestión comercial para Repuestos Guevara. Está construida con Flask y SQLAlchemy y se configura para MySQL 8 con `utf8mb4` e InnoDB. El proyecto incluye una base SQLite local como alternativa de evaluación rápida; para operar el negocio, configura MySQL en `.env`.

Para ver el diseño sin instalar dependencias, abre `preview.html` en el navegador. Esa página es solo una muestra visual sin cifras ni conexión a la base; la aplicación real se ejecuta con los pasos de instalación de abajo.

## Qué incluye

- Inicio de sesión privado, contraseñas con hash, protección CSRF, bloqueo temporal de intentos fallidos por IP y roles de administrador, vendedor, almacenero y consulta.
- Dashboard conectado a la base, con ventas del día y mes, productos, alertas de stock, actividad reciente y gráfica de siete días.
- Catálogo de productos con búsqueda por nombre, SKU o código de barras; edición de todos los datos comerciales, foto reemplazable/eliminable, categorías y marcas. Incluye imágenes optimizadas de ejemplo para cinco repuestos.
- Gestión de categorías y marcas: crear, editar, activar, desactivar y eliminar. Si una opción ya está asociada a productos, se archiva para conservar esas referencias.
- Control de existencias con historial de movimientos y ajustes justificados; no permite stock negativo.
- Registro y edición de proveedores (marcas distribuidas y condiciones comerciales) y clientes (motocicleta y notas), con protección para el cliente predeterminado Consumidor final. Los registros de muestra pueden marcarse como demostración.
- Eliminación segura de productos, clientes y proveedores: conserva como inactivos los registros ligados a stock, ventas o compras anteriores.
- Compras con múltiples líneas. Una compra pendiente no cambia el stock; la recepción genera movimientos y actualiza el costo promedio ponderado. No se puede recibir dos veces.
- Punto de venta con validación del lado servidor, descuento limitado por rol, control de existencias, pago de un método por venta, número de operación e idempotencia ante doble envío.
- Comprobante comercial imprimible, historial de ventas, apertura y cierre de caja, gastos operativos, reportes por periodo y exportación de ventas a CSV.
- Administración de cuentas, configuración del negocio y registro de auditoría.
- Diseño adaptable para escritorio, tablet y móvil, con el logotipo original integrado sin recortarlo ni deformarlo.

## Alcance que todavía requiere una fase adicional

Este paquete cubre una primera versión operativa de los procesos principales; no implementa cada punto del prompt maestro. En particular, aún faltan devoluciones/anulaciones con reversa transaccional, pagos combinados o saldos por cobrar, PDF descargable y formatos fiscales, galería de varias fotos, compatibilidad estructurada por marca/modelo/año, notificaciones persistentes, compras cancelables/detalladas, exportación a Excel, reportes completos de compras/gastos y respaldos automáticos programados. El comprobante que genera es comercial y nunca se presenta como factura fiscal.

El logotipo original está en `app/static/img/logo.png`. La aplicación muestra el archivo en acceso, menú, vista previa y comprobantes; conserva el PNG original y ajusta solo su tamaño de presentación.

## Requisitos

- Windows 10/11.
- Python 3.11 o posterior.
- MySQL Server 8.0 o posterior para uso comercial.
- Git no es necesario para instalar.

## Instalación en PowerShell

1. Descomprime el ZIP y abre PowerShell dentro de la carpeta `repuestos-guevara`.

2. Crea y activa un entorno virtual:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Si PowerShell bloquea la activación, habilítala solo para esta sesión y vuelve a activar:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
   .\.venv\Scripts\Activate.ps1
   ```

3. Instala las dependencias:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Prepara MySQL. En una consola autenticada como administrador de MySQL:

   ```sql
   CREATE DATABASE repuestos_guevara CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   CREATE USER 'rg_user'@'localhost' IDENTIFIED BY 'elige-una-clave-larga';
   GRANT ALL PRIVILEGES ON repuestos_guevara.* TO 'rg_user'@'localhost';
   FLUSH PRIVILEGES;
   ```

5. Crea tu archivo local de configuración:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edita `.env` y reemplaza `SECRET_KEY` y `DATABASE_URL`. Puedes generar una clave aleatoria así:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Usa una URI como `mysql+pymysql://rg_user:TU_CLAVE@127.0.0.1/repuestos_guevara?charset=utf8mb4`. Si la contraseña contiene caracteres reservados de URL (`@`, `:`, `/`, `#`), codifícala antes de colocarla en la URI.

6. Inicializa las migraciones y la base de datos:

   ```powershell
   $env:FLASK_APP = "run.py"
   flask db init
   flask db migrate -m "Esquema inicial"
   flask db upgrade
   flask seed-reference
   flask create-admin
   ```

   `create-admin` solicita nombre, correo y contraseña de al menos 12 caracteres. No hay credenciales predeterminadas ni registro público.

7. Inicia el servidor local:

   ```powershell
   flask run
   ```

8. Abre [http://127.0.0.1:5000](http://127.0.0.1:5000) en el navegador. Para entrar desde otra computadora de la red, configura primero un servidor de producción y su proxy HTTPS; `flask run` es solo para desarrollo local.

### Vista rápida sin MySQL

Si no tienes MySQL instalado, deja `DATABASE_URL=` vacío en `.env` y usa la base SQLite local para revisar el diseño y los flujos. Ejecuta los comandos de migración y los comandos Flask como arriba. SQLite no reemplaza a MySQL como base del negocio ni se recomienda para varios usuarios simultáneos.

## Pruebas

Con el entorno virtual activado:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas cubren el descuento de existencias una sola vez, la recepción de compras y el acceso autenticado. Ejecuta también el recorrido del negocio con una base de prueba antes de operar con datos reales.

## Imágenes, migraciones y respaldos

- Las imágenes que se suben desde el formulario se guardan en `app/static/uploads/products/`, con nombre aleatorio y salida WebP. El catálogo también ofrece cinco imágenes WebP incluidas en `app/static/img/products/`. MySQL conserva únicamente la ruta de cada imagen.
- Al abrir por primera vez la aplicación después de actualizarla, se crean las tablas adicionales de perfil de clientes y proveedores si aún no existen; no se modifican las tablas comerciales existentes.
- Al modificar modelos en una versión futura, usa `flask db migrate -m "describe el cambio"` y revisa el archivo creado antes de `flask db upgrade`.
- Para copias manuales de MySQL, desde PowerShell usa `mysqldump --user rg_user --password --single-transaction --default-character-set=utf8mb4 repuestos_guevara > .\respaldo-repuestos-guevara.sql`. MySQL solicitará la contraseña. Guarda los respaldos cifrados fuera de `app/static` y limita el acceso.
- Para restaurar en una base preparada: `Get-Content .\respaldo-repuestos-guevara.sql | mysql --user rg_user --password repuestos_guevara`. Haz una copia del estado actual antes de restaurar.
- Define una tarea programada de Windows para ejecutar el respaldo según la frecuencia que requiera el negocio. Este paquete no crea una tarea automática ni guarda copias dentro del directorio web.

## Seguridad y puesta en producción

Mantén `.env` fuera del control de versiones, define una `SECRET_KEY` propia, usa una cuenta MySQL con privilegios limitados a esta base, sirve la aplicación detrás de HTTPS y configura `SESSION_COOKIE_SECURE=1` cuando TLS esté configurado. El límite de intentos de acceso de esta versión reside en memoria del proceso y debe sustituirse por un limitador persistente al escalar a varios procesos. Revisa y restaura copias de seguridad en un entorno de prueba antes de depender de ellas.
