# Instalación de Dependencias

El módulo `l10n_ar_import_bill_ce` requiere las siguientes dependencias de Python:

## Dependencias requeridas

- `pandas` >= 1.3.0
- `openpyxl` >= 3.0.0

## Instalación

### Opción 1: Instalación manual

Instala las dependencias en el entorno de Python donde corre Odoo:

```bash
pip install pandas>=1.3.0 openpyxl>=3.0.0
```

### Opción 2: Usar requirements.txt

El módulo incluye un archivo `requirements.txt` con las dependencias:

```bash
pip install -r l10n_ar_import_bill_ce/requirements.txt
```

### Opción 3: Instalación en el servidor

Si Odoo está corriendo en un servidor, instala las dependencias en el entorno virtual de Odoo:

```bash
# Si usas un entorno virtual
source /ruta/al/venv/bin/activate
pip install pandas openpyxl

# O si Odoo está instalado globalmente
sudo pip3 install pandas openpyxl
```

## Verificación

Para verificar que las dependencias están instaladas:

```bash
python3 -c "import pandas; import openpyxl; print('Dependencias OK')"
```

## Nota

Odoo mostrará un error si las dependencias no están instaladas al intentar instalar el módulo. Asegúrate de instalar estas dependencias antes de instalar el módulo.

