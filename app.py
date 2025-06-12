import os
from flask import Flask, render_template, request as flask_request, redirect, url_for, flash
import requests
from dotenv import load_dotenv
import json
import time

load_dotenv()

app = Flask(__name__)

# --- CONFIGURACIÓN ---
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'una-llave-secreta-muy-dificil-de-adivinar')

KOBO_API_TOKEN = os.getenv('KOBO_API_TOKEN')
GEO_ASSET_UID = os.getenv('GEO_ASSET_UID')
PARCELA_ASSET_UID = os.getenv('PARCELA_ASSET_UID')
PADRON_API_UID = os.getenv('PADRON_API_UID')
KOBO_BASE_URL = os.getenv('KOBO_BASE_URL')

# URLs de las APIs
GEO_API_URL = f'{KOBO_BASE_URL}/api/v2/assets/{GEO_ASSET_UID}/data/?format=json'
PARCELA_API_URL = f'{KOBO_BASE_URL}/api/v2/assets/{PARCELA_ASSET_UID}/data/?format=json'
PADRON_API_URL = f'{KOBO_BASE_URL}/api/v2/assets/{PADRON_API_UID}/data/?format=json'


# --- CACHE EN MEMORIA Y PRE-PROCESAMIENTO (LA GRAN MEJORA) ---
_cache = {
    "data": None,
    "last_updated": 0
}
# Cache por 1 hora (3600 segundos). Puedes ajustar este valor.
CACHE_DURATION = 4  

def process_data_for_lookup(geo_records, parcela_records, padron_records):
    """
    Convierte las listas de registros en diccionarios para búsquedas O(1).
    Esto acelera drásticamente la aplicación.
    """
    processed = {
        "geo_by_codigo_parcela": {rec.get('georeferenciacion/codigo_parcela'): rec for rec in geo_records if rec.get('georeferenciacion/codigo_parcela')},
        "parcela_by_id_parcela": {rec.get('id_parcela'): rec for rec in parcela_records if rec.get('id_parcela')},
        "padron_by_socio": {rec.get('socio'): rec for rec in padron_records if rec.get('socio')}
    }
    return processed

def get_processed_data():
    """
    Obtiene los datos desde la API o desde la cache si aún es válida.
    Esta función es el núcleo de la optimización.
    """
    current_time = time.time()
    # Si la cache tiene datos y no ha expirado, la usamos.
    if _cache["data"] and (current_time - _cache["last_updated"]) < CACHE_DURATION:
        print("--- Usando datos desde la CACHE ---")
        return _cache["data"]

    # Si la cache está vacía o expiró, obtenemos datos frescos.
    print("--- Obteniendo datos frescos desde la API de KoboToolbox... ---")
    
    # Aumenta el timeout para peticiones grandes
    timeout_seconds = 30 
    
    geo_data_response = fetch_kobo_data(GEO_API_URL, timeout_seconds)
    parcela_data_response = fetch_kobo_data(PARCELA_API_URL, timeout_seconds)
    padron_data_response = fetch_kobo_data(PADRON_API_URL, timeout_seconds)
    
    if not (geo_data_response and parcela_data_response and padron_data_response):
        flash("Error crítico: no se pudieron obtener los datos de una o más APIs de Kobo. Intente de nuevo más tarde.", "error")
        # Si ya teníamos datos viejos, es mejor devolverlos que nada.
        return _cache["data"] if _cache["data"] else None

    geo_records = geo_data_response.get('results', [])
    parcela_records = parcela_data_response.get('results', [])
    padron_records = padron_data_response.get('results', [])
    
    processed_data = process_data_for_lookup(geo_records, parcela_records, padron_records)
    
    # Actualizamos la cache
    _cache["data"] = processed_data
    _cache["last_updated"] = current_time
    
    print("--- Cache actualizada con datos frescos. ---")
    return processed_data

# --- FUNCIONES AUXILIARES (con timeout ajustable) ---
def fetch_kobo_data(api_url, timeout=15):
    """Función genérica para obtener datos de cualquier API de Kobo"""
    headers = {'Authorization': f'Token {KOBO_API_TOKEN}'}
    try:
        # Usar un limit alto para traer todos los datos de una vez
        response = requests.get(api_url, headers=headers, params={'limit': 5000}, timeout=timeout) # Aumentado el limit por si acaso
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"Timeout ({timeout}s) al obtener datos de: {api_url}")
        return None
    except requests.exceptions.HTTPError as http_err:
        print(f"Error HTTP: {http_err}")
        print(f"Respuesta (código {http_err.response.status_code}): {http_err.response.text[:500]}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error al decodificar JSON de {api_url}: {e}")
        return None

# Las funciones de parseo no necesitan cambios
def parse_gps_point(gps_string):
    if not gps_string or not isinstance(gps_string, str): return None
    parts = gps_string.split(' ')
    if len(parts) >= 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180: return [lat, lon]
        except ValueError: return None
    return None

def parse_polygon(polygon_string):
    if not polygon_string or not isinstance(polygon_string, str): return []
    coordinates = []
    for point_str in polygon_string.split(';'):
        parts = point_str.strip().split(' ')
        if len(parts) >= 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180: coordinates.append([lat, lon])
            except ValueError: continue
    return coordinates

def extract_gps_details(gps_string):
    if not gps_string or not isinstance(gps_string, str): return None
    parts = gps_string.split(' ')
    if len(parts) >= 4:
        try:
            return {'latitud': float(parts[0]), 'longitud': float(parts[1]), 'altitud': float(parts[2]), 'precision': float(parts[3])}
        except ValueError: return None
    return None

# --- RUTA PRINCIPAL (AHORA MUCHO MÁS RÁPIDA) ---
@app.route('/')
def index():
    search_id_parcela = flask_request.args.get('search_id_parcela', '').strip()
    
    # MODIFICADO: Usa la función de cache
    processed_data = get_processed_data()
    if not processed_data:
        # Si la carga inicial falló, muestra un error y no continúa.
        return render_template('index.html', message="Error al cargar los datos base. Revise la conexión con KoboToolbox.", default_map_center_js=json.dumps([16.9202568, -92.5100693]), default_map_zoom=13)

    selected_geo_record = None
    selected_parcela_record = None
    center_coords_for_js = None
    polygon_coords_for_js = []
    message = None
    gps_details = None

    if search_id_parcela:
        # MODIFICADO: Búsqueda súper rápida usando el diccionario pre-procesado
        selected_geo_record = processed_data["geo_by_codigo_parcela"].get(search_id_parcela)

        if selected_geo_record:
            gps_point_str = selected_geo_record.get('georeferenciacion/gps')
            gps_details = extract_gps_details(gps_point_str)
            if gps_details:
                selected_geo_record.update({
                    'gps_latitud': f"{gps_details['latitud']:.6f}",
                    'gps_longitud': f"{gps_details['longitud']:.6f}",
                    'gps_altitud': f"{gps_details['altitud']:.2f} m",
                    'gps_precision': f"{gps_details['precision']:.2f} m"
                })
            
            center_coords_for_js = parse_gps_point(gps_point_str)
            polygon_coords_for_js = parse_polygon(selected_geo_record.get('georeferenciacion/poligono'))

            # MODIFICADO: Búsqueda rápida de la parcela correspondiente
            selected_parcela_record = processed_data["parcela_by_id_parcela"].get(search_id_parcela)
            if selected_parcela_record:
                poligono_data_str = selected_geo_record.get('georeferenciacion/poligono')
                if poligono_data_str:
                    selected_parcela_record['georeferenciacion/poligono'] = poligono_data_str

            # MODIFICADO: Búsqueda rápida del socio en el padrón
            socio_nombre = selected_geo_record.get('georeferenciacion/socio')
            selected_padron_record = processed_data["padron_by_socio"].get(socio_nombre)
            
            if selected_padron_record:
                selected_geo_record.update({
                    'productor_id': selected_padron_record.get('id_productor', 'N/A'),
                    'productor_region': selected_padron_record.get('region', 'N/A'),
                    'productor_grupo': selected_padron_record.get('grupo_trabajo', 'N/A'),
                    'productor_curp': selected_padron_record.get('curp', 'N/A'),
                    'productor_rfc': selected_padron_record.get('rfc', 'N/A'),
                    'productor_folio_cafetalero': selected_padron_record.get('folio_cafetalero', 'N/A'),
                    'productor_fecha_nacimiento': selected_padron_record.get('fecha_nacimiento', 'N/A'),
                    'productor_genero': 'Masculino' if selected_padron_record.get('genero') == 'H' else 'Femenino',
                    'productor_estatus': selected_padron_record.get('estatus', 'N/A'),
                    'productor_ingreso': selected_padron_record.get('ingreso', 'N/A'),
                    'productor_num_parcelas': selected_padron_record.get('numero_parcelas', 'Dato no encontrado en padrón'),
                    'productor_activo': 'Sí' if selected_padron_record.get('activo') == '1' else 'No'
                })
            else:
                selected_geo_record['productor_num_parcelas'] = "Socio no encontrado en padrón"
                message = f"Parcela encontrada, pero el socio '{socio_nombre}' no fue hallado en el padrón. Verifique la consistencia de los datos."

        else:
            message = f"No se encontró ninguna parcela con el ID: {search_id_parcela}"
    else:
        message = "Por favor, ingrese un ID de Parcela para buscar."

    geo_headers_map = {
        'georeferenciacion/municipio': 'Municipio',
        'georeferenciacion/localidad': 'Comunidad',
        'productor_grupo': 'Grupo de Trabajo',
        'georeferenciacion/socio': 'Socio',
        'productor_num_parcelas': 'Número de parcelas',
        'georeferenciacion/codigo_parcela': 'Código de la parcela',
        'georeferenciacion/nombre_parcela': 'Nombre Parcela',
        'georeferenciacion/area_gps_ha': 'Superficie GPS (ha)',
        'gps_latitud': 'Latitud',
        'gps_longitud': 'Longitud',
        'gps_altitud': 'Altitud',
        'gps_precision': 'Precisión GPS',
        'productor_genero': 'Género',
    }

    parcela_headers_map = {
        'superficie': 'Superficie declarada (ha)',
        'norte': 'Cultivo al norte',
        'norte_propietario': 'Colindante norte',
        'sur': 'Cultivo al sur',
        'sur_propietario': 'Colindante sur',
        'este': 'Cultivo al este',
        'este_propietario': 'Colindante este',
        'oeste': 'Cultivo oeste',
        'oeste_propietario': 'Colindante oeste',
        'georeferenciacion/poligono': 'Coordenadas del Polígono',
    }

    return render_template(
        'index.html',
        geo_record=selected_geo_record,
        parcela_record=selected_parcela_record,
        geo_headers=geo_headers_map,
        parcela_headers=parcela_headers_map,
        gps_details=gps_details,
        center_coords_js=json.dumps(center_coords_for_js),
        polygon_coords_js=json.dumps(polygon_coords_for_js),
        default_map_center_js=json.dumps([16.9202568, -92.5100693]),
        default_map_zoom=13,
        current_search_id=search_id_parcela,
        message=message
    )

@app.route('/update_location', methods=['POST'])
def update_location():
    
    # ... (tu lógica para obtener record_id, new_gps_coords_str, etc.)
    # ... (tu lógica para hacer la petición PATCH a la API de Kobo)
    
    # Ejemplo simplificado de tu lógica
    record_id = flask_request.form.get('record_id')
    search_id_parcela = flask_request.form.get('search_id_parcela')
    # ... hacer la actualización...
    # if la_actualizacion_fue_exitosa:

    global _cache
    _cache["data"] = None
    _cache["last_updated"] = 0
    print("--- Cache invalidada debido a una actualización de datos. ---")

    flash(f'¡Ubicación de la parcela {search_id_parcela} actualizada correctamente! La cache de datos se refrescará en la siguiente carga.', 'success')
    return redirect(url_for('index', search_id_parcela=search_id_parcela))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)