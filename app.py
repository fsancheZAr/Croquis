import os
from flask import Flask, render_template, request as flask_request, redirect, url_for, flash
import requests
from dotenv import load_dotenv
import json

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

# --- FUNCIONES AUXILIARES ---
def fetch_kobo_data(api_url):
    """Función genérica para obtener datos de cualquier API de Kobo"""
    headers = {'Authorization': f'Token {KOBO_API_TOKEN}'}
    try:
        response = requests.get(api_url, headers=headers, params={'limit': 2000}, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"Timeout al obtener datos de: {api_url}")
        return None
    except requests.exceptions.HTTPError as http_err:
        print(f"Error HTTP: {http_err}")
        print(f"Respuesta (código {response.status_code}): {response.text[:500]}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error al decodificar JSON: {e}")
        return None

def parse_gps_point(gps_string):
    if not gps_string or not isinstance(gps_string, str):
        return None
    parts = gps_string.split(' ')
    if len(parts) >= 2:
        try:
            lat = float(parts[0])
            lon = float(parts[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                 return [lat, lon]
            else:
                return None
        except ValueError:
            return None
    return None

def parse_polygon(polygon_string):
    if not polygon_string or not isinstance(polygon_string, str):
        return []
    points_str_array = polygon_string.split(';')
    coordinates = []
    for point_str in points_str_array:
        parts = point_str.strip().split(' ')
        if len(parts) >= 2:
            try:
                lat = float(parts[0])
                lon = float(parts[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    coordinates.append([lat, lon])
            except ValueError:
                continue
    return coordinates

def extract_gps_details(gps_string):
    if not gps_string or not isinstance(gps_string, str):
        return None
    parts = gps_string.split(' ')
    if len(parts) >= 4:
        try:
            return {
                'latitud': float(parts[0]),
                'longitud': float(parts[1]),
                'altitud': float(parts[2]),
                'precision': float(parts[3])
            }
        except ValueError:
            return None
    return None

def find_record_by_id(records_list, search_field, search_value):
    """Función auxiliar para buscar un registro por un campo específico"""
    if not records_list or not search_value:
        return None
    
    for record in records_list:
        if record.get(search_field) == search_value:
            return record
    return None

# --- RUTAS ---
@app.route('/')
def index():
    search_id_parcela = flask_request.args.get('search_id_parcela', None)
    print(f"Buscando ID Parcela: {search_id_parcela}")

    # Obtener datos de todas las APIs
    geo_data_response = fetch_kobo_data(GEO_API_URL)
    parcela_data_response = fetch_kobo_data(PARCELA_API_URL)
    nueva_data_response = fetch_kobo_data(PADRON_API_URL)

    # Variables para almacenar registros seleccionados
    selected_geo_record = None
    selected_parcela_record = None
    selected_nueva_record = None
    
    # Variables para el mapa
    center_coords_for_js = None
    polygon_coords_for_js = []
    message = None
    gps_details = None

    # Procesar datos de GEO (API principal)
    if geo_data_response and geo_data_response.get('results'):
        geo_records = geo_data_response['results']
        
        if search_id_parcela:
            selected_geo_record = find_record_by_id(
                geo_records, 
                'georeferenciacion/codigo_parcela', 
                search_id_parcela
            )
            
            if not selected_geo_record:
                message = f"No se encontró registro GEO para ID: {search_id_parcela}"
        else:
            message = "Por favor, ingrese un ID de Parcela para buscar."

        if selected_geo_record:
            gps_point_str = selected_geo_record.get('georeferenciacion/gps')
            gps_details = extract_gps_details(gps_point_str)
            
            if gps_details:
                selected_geo_record['gps_latitud'] = f"{gps_details['latitud']:.6f}"
                selected_geo_record['gps_longitud'] = f"{gps_details['longitud']:.6f}"
                selected_geo_record['gps_altitud'] = f"{gps_details['altitud']:.2f} m"
                selected_geo_record['gps_precision'] = f"{gps_details['precision']:.2f} m"
            
            center_coords_for_js = parse_gps_point(gps_point_str)
            polygon_coords_for_js = parse_polygon(selected_geo_record.get('georeferenciacion/poligono'))

            codigo_parcela = selected_geo_record.get('georeferenciacion/codigo_parcela')
            
            if codigo_parcela and parcela_data_response and parcela_data_response.get('results'):
                selected_parcela_record = find_record_by_id(
                    parcela_data_response['results'],
                    'id_parcela',
                    codigo_parcela
                )
                
                if selected_parcela_record:
                    poligono_data_str = selected_geo_record.get('georeferenciacion/poligono')
                    if poligono_data_str:
                        selected_parcela_record['georeferenciacion/poligono'] = poligono_data_str
            
            socio_nombre = selected_geo_record.get('georeferenciacion/socio')
            if socio_nombre and nueva_data_response and nueva_data_response.get('results'):
                selected_nueva_record = find_record_by_id(
                    nueva_data_response['results'],
                    'socio',
                    socio_nombre
                )
                
                if selected_nueva_record:
                    selected_geo_record['productor_id'] = selected_nueva_record.get('id_productor', 'N/A')
                    selected_geo_record['productor_region'] = selected_nueva_record.get('region', 'N/A')
                    selected_geo_record['productor_grupo'] = selected_nueva_record.get('grupo_trabajo', 'N/A')
                    selected_geo_record['productor_curp'] = selected_nueva_record.get('curp', 'N/A')
                    selected_geo_record['productor_rfc'] = selected_nueva_record.get('rfc', 'N/A')
                    selected_geo_record['productor_folio_cafetalero'] = selected_nueva_record.get('folio_cafetalero', 'N/A')
                    selected_geo_record['productor_fecha_nacimiento'] = selected_nueva_record.get('fecha_nacimiento', 'N/A')
                    selected_geo_record['productor_genero'] = 'Masculino' if selected_nueva_record.get('genero') == 'H' else 'Femenino' if selected_nueva_record.get('genero') == 'M' else 'N/A'
                    selected_geo_record['productor_estatus'] = selected_nueva_record.get('estatus', 'N/A')
                    selected_geo_record['productor_ingreso'] = selected_nueva_record.get('ingreso', 'N/A')
                    selected_geo_record['productor_num_parcelas'] = selected_nueva_record.get('numero_parcelas', 'N/A')
                    selected_geo_record['productor_activo'] = 'Sí' if selected_nueva_record.get('activo') == '1' else 'No'

    # Definir qué campos mostrar
    geo_headers_map = {
        'georeferenciacion/socio': 'Socio',
        'georeferenciacion/localidad': 'Comunidad',
        'georeferenciacion/municipio': 'Municipio',
        'productor_num_parcelas': 'Número de Parcelas',
        "georeferenciacion/numero_parcela": "Numero de parcela",
        'georeferenciacion/codigo_parcela': 'Código de la parcela',
        'georeferenciacion/nombre_parcela': 'Nombre Parcela',
        'georeferenciacion/area_gps_ha': 'Superficie calculada por el sistema (ha)',
        'georeferenciacion/anio_incio_cultivo': 'Año de inicio de cultivo',
        'gps_latitud': 'Latitud',
        'gps_longitud': 'Longitud',
        'gps_altitud': 'Altitud',
        'gps_precision': 'Precisión GPS',
        'productor_grupo': 'Grupo de Trabajo',
        'productor_genero': 'Género',
        'productor_estatus': 'Estatus',
    }

    parcela_headers_map = {
        'superficie': 'Superficie declarada por el productor (ha)',
        'norte': 'Cultivo al norte',
        'norte_propietario': 'Propietario',
        'sur': 'Cultivo al sur',
        'sur_propietario': 'Propietario',
        'este': 'Cultivo al Este',
        'este_propietario': 'Propietario',
        'oeste': 'Cultivo Oeste',
        'oeste_propietario': 'Propietario',
        'georeferenciacion/poligono': 'GPS Polígono',
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
        current_search_id=search_id_parcela if search_id_parcela else "",
        message=message
    )

@app.route('/update_location', methods=['POST'])
def update_location():
    record_id = flask_request.form.get('record_id')
    new_gps_coords_str = flask_request.form.get('new_gps_coords')
    search_id_parcela = flask_request.form.get('search_id_parcela')

    if not record_id or not new_gps_coords_str:
        flash('Error: Faltan datos críticos (ID de registro o coordenadas) para la actualización.', 'error')
        # Redirigir a la página principal si no hay ID de parcela
        return redirect(url_for('index', search_id_parcela=search_id_parcela if search_id_parcela else ''))

    try:
        kobo_gps_string = f"{new_gps_coords_str} 0 0"
        payload = {"submission": {"georeferenciacion/gps": kobo_gps_string}}
        edit_api_url = f'{KOBO_BASE_URL}/api/v2/assets/{GEO_ASSET_UID}/data/{record_id}/'
        headers = {'Authorization': f'Token {KOBO_API_TOKEN}'}

        print(f"Intentando enviar PATCH a: {edit_api_url}")
        print(f"Payload: {json.dumps(payload)}")

        response = requests.patch(edit_api_url, headers=headers, json=payload, timeout=20)
        
        # Esta línea lanzará la excepción si el código de estado es 4xx o 5xx
        response.raise_for_status()

        flash(f'¡Ubicación de la parcela {search_id_parcela} actualizada correctamente!', 'success')
        print(f"Éxito al actualizar. Status: {response.status_code}")

    except requests.exceptions.HTTPError as http_err:
        # Ahora estamos seguros de que 'response' existe si entramos en este bloque
        error_detail = f"Respuesta del servidor: {http_err.response.status_code} - {http_err.response.text[:300]}"
        error_message = f"Error HTTP al actualizar. {error_detail}"
        print(error_message) # Imprime el error completo en la consola
        flash(error_message, 'error')
    except requests.exceptions.Timeout:
        error_message = "Error: La petición a KoBoToolbox tardó demasiado en responder (Timeout)."
        print(error_message)
        flash(error_message, 'error')
    except requests.exceptions.RequestException as e:
        # Error genérico de red (DNS, conexión rechazada, etc.)
        error_message = f"Error de conexión al intentar contactar a KoBoToolbox: {e}"
        print(error_message)
        flash(error_message, 'error')
    except Exception as e:
        error_message = f"Ocurrió un error inesperado en el servidor: {e}"
        print(error_message)
        flash(error_message, 'error')
    
    # Redirigir siempre, incluso si hay error
    return redirect(url_for('index', search_id_parcela=search_id_parcela if search_id_parcela else ''))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)