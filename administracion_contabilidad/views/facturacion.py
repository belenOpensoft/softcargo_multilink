import base64
import json
import logging
import re
import uuid
from functools import reduce
from operator import or_

from django.contrib.auth.decorators import login_required
from django.core.checks import messages
from django.core.exceptions import ObjectDoesNotExist
from django.forms import model_to_dict
from django.shortcuts import render
from django.views.decorators.http import require_POST
from reportlab.lib.validators import isNumber
from zeep.helpers import serialize_object

from administracion_contabilidad.views.facturacion_electronica.ucfe_client import UCFEClient
from cargosystem.settings import BASE_DIR
from expaerea.models import ExportEmbarqueaereo, ExportCargaaerea, VEmbarqueaereo as EA, ExportReservas, \
    ExportServiceaereo
from expmarit.models import ExpmaritEmbarqueaereo, ExpmaritCargaaerea, VEmbarqueaereo as EM, ExpmaritReservas, \
    ExpmaritServiceaereo
from expterrestre.models import ExpterraEmbarqueaereo, ExpterraCargaaerea, VEmbarqueaereo as ET, ExpterraReservas, \
    ExpterraServiceaereo
from impaerea.models import ImportEmbarqueaereo, ImportCargaaerea, VEmbarqueaereo as IA, ImportConexaerea, \
    ImportReservas, ImportServiceaereo
from impterrestre.models import ImpterraEmbarqueaereo, ImpterraCargaaerea, VEmbarqueaereo as IT, ImpterraReservas, \
    ImpterraServiceaereo
from mantenimientos.models import Clientes, Servicios, Monedas, Vapores, Ciudades, Paises
from administracion_contabilidad.forms import Factura, RegistroCargaForm, VentasDetalleTabla
from administracion_contabilidad.models import Boleta, Asientos, Movims, Infofactura, \
    VistaGastosPreventa, Dolar, Factudif, VPreventas, VistaVentas, Impuvtas
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from datetime import datetime
from django.db import transaction
from django.db.models import F, Max, Q
from impomarit.models import VGastosHouse, Envases, Cargaaerea, Embarqueaereo, VEmbarqueaereo as IM, Reservas, \
    Serviceaereo, BloqueoEdicion
from decimal import Decimal
from administracion_contabilidad.forms import pdfForm
from django.utils.timezone import now, timedelta
from django.http import JsonResponse
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from xml.sax.saxutils import escape

param_busqueda = {
    1: 'autogenerado__icontains',
    2: 'fecha__icontains',
    3: 'num_completo__icontains',
    4: 'cliente__icontains',
    5: 'posicion__icontains',
    6: 'monto__icontains',
    7: 'iva__icontains',
    8: 'total__icontains',
}

columns_table = {
    0:'vacia',
    1: 'autogenerado',
    2: 'fecha',
    3: 'num_completo',
    4: 'cliente',
    5: 'posicion',
    6: 'monto',
    7: 'iva',
    8: 'total',
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(str(BASE_DIR) + "/logs/facturacion.log", mode="a", encoding="utf-8")
    ]
)

def source_facturacion(request):
    args = {str(i): request.GET.get(f'columns[{i}][search][value]', '') for i in range(1,9)}
    filtro = get_argumentos_busqueda(**args)

    start  = int(request.GET['start'])
    length = int(request.GET['length'])
    buscar = request.GET.get('buscar', '')
    que_buscar = request.GET.get('que_buscar', '')

    if buscar:
        filtro[que_buscar] = buscar

    order = get_order(request, columns_table)  # p.ej. ['cliente', '-fecha']

    base = VistaVentas.objects.filter(**filtro)

    # 1 fila por autogenerado (fecha más reciente; si empata, pk más alta)
    qs = (base
          .annotate(rn=Window(
              expression=RowNumber(),
              partition_by=[F('autogenerado')],
              order_by=[F('fecha').desc(), F('pk').desc()],
          ))
          .filter(rn=1))

    if order:
        qs = qs.order_by(*order)

    # conteos
    total_all = VistaVentas.objects.values('autogenerado').distinct().count()
    total_filtered = base.values('autogenerado').distinct().count()

    page = list(qs[start:start+length])

    return JsonResponse({
        'data': get_data(page),
        'length': length,
        'draw': request.GET['draw'],
        'recordsTotal': total_all,
        'recordsFiltered': total_filtered,
    })

def source_facturacion_old(request):
    args = {
        '1': request.GET['columns[1][search][value]'],
        '2': request.GET['columns[2][search][value]'],
        '3': request.GET['columns[3][search][value]'],
        '4': request.GET['columns[4][search][value]'],
        '5': request.GET['columns[5][search][value]'],
        '6': request.GET['columns[6][search][value]'],
        '7': request.GET['columns[7][search][value]'],
        '8': request.GET['columns[8][search][value]'],
    }

    filtro = get_argumentos_busqueda(**args)
    start = int(request.GET['start'])
    length = int(request.GET['length'])
    buscar = str(request.GET['buscar'])
    que_buscar = str(request.GET['que_buscar'])

    if len(buscar) > 0:
        filtro[que_buscar] = buscar

    order = get_order(request, columns_table)

    # Agrupar por autogenerado y obtener fecha más reciente
    agrupados = (VistaVentas.objects
                 .filter(**filtro)
                 .values('autogenerado')
                 .annotate(fecha_max=Max('fecha'))
                 )

    # Ahora traemos todos los registros que coinciden con autogenerado y fecha_max
    todo = VistaVentas.objects.filter(
        reduce(
            or_,
            [Q(autogenerado=row['autogenerado'], fecha=row['fecha_max']) for row in agrupados]
        )
    ).order_by(*order)

    # Agrupar manualmente en Python por autogenerado (por si hay más de uno con misma fecha)
    vista_unicos = {}
    for row in todo:
        if row.autogenerado not in vista_unicos:
            vista_unicos[row.autogenerado] = row

    # Convertir a lista y paginar
    registros_finales = list(vista_unicos.values())
    resultado = {
        'data': get_data(registros_finales[start:start + length]),
        'length': length,
        'draw': request.GET['draw'],
        'recordsTotal': len(vista_unicos),
        'recordsFiltered': len(vista_unicos),
    }
    return JsonResponse(resultado)

def get_argumentos_busqueda(**kwargs):
    try:
        result = {}
        for row in kwargs:
            if len(kwargs[row]) > 0:
                result[param_busqueda[int(row)]] = kwargs[row]
        return result
    except Exception as e:
        raise TypeError(e)

def get_data(registros_filtrados):
    try:
        data = []
        for registro in registros_filtrados:
            registro_json = []
            registro_json.append(str(registro.tipo))
            registro_json.append('' if registro.autogenerado is None else str(registro.autogenerado))
            registro_json.append('' if registro.fecha is None else registro.fecha.strftime('%Y-%m-%d'))
            registro_json.append('' if registro.num_completo is None else str(registro.num_completo))
            registro_json.append('' if registro.cliente is None else str(registro.cliente))
            registro_json.append('' if registro.posicion is None else str(registro.posicion))
            registro_json.append('' if registro.monto is None else str(registro.monto))
            registro_json.append('' if registro.iva is None else str(registro.iva))
            registro_json.append('' if registro.total is None else str(registro.total))
            registro_json.append('' if registro.nrocliente is None else str(registro.nrocliente))
            registro_json.append('' if registro.numero is None else str(registro.numero))
            data.append(registro_json)
        return data
    except Exception as e:
        raise TypeError(e)

def get_order(request, columns):
    try:
        result = []
        order_column = request.GET['order[0][column]']
        order_dir = request.GET['order[0][dir]']
        order = columns[int(order_column)]
        if order_dir == 'desc':
            order = '-' + columns[int(order_column)]
        result.append(order)
        i = 1
        while i > 0:
            try:
                order_column = request.GET['order[' + str(i) + '][column]']
                order_dir = request.GET['order[' + str(i) + '][dir]']
                order = columns[int(order_column)]
                if order_dir == 'desc':
                    order = '-' + columns[int(order_column)]
                result.append(order)
                i += 1
            except Exception as e:
                i = 0
        result.append('fecha')
        return result
    except Exception as e:
        raise TypeError(e)

@login_required(login_url='/login')
def facturacion_view(request):
    if request.user.has_perms(["administracion_contabilidad.view_boleta", ]):
        form = Factura(request.POST or None)
        detalle = VentasDetalleTabla(request.POST or None)
        return render(request, 'facturacion.html', {'form': form,'form_pdf': pdfForm(),'complemento':RegistroCargaForm(),'detalle':detalle})
    else:
        messages.error(request, 'No tiene permisos para realizar esta accion.')
        return HttpResponseRedirect('/')

def buscar_cliente(request):
    #revisar
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
        query = request.GET.get('term', '').strip()  # Obtener y limpiar el término de búsqueda
        clientes = Clientes.objects.filter(empresa__istartswith=query)[:10]  # Filtra por inicio y limita a 10 resultados
        results = [{'id': cliente.codigo, 'text': cliente.empresa} for cliente in clientes]
        return JsonResponse(results, safe=False)

    return JsonResponse({'error': 'Solicitud inválida'}, status=400)


def buscar_clientes(request):
    if request.method == "GET":
        cliente_id = request.GET.get("id")
        cliente = Clientes.objects.filter(codigo=cliente_id).first()

        if cliente:
            data = {
                'codigo': cliente.codigo,
                'empresa': cliente.empresa,
                'ruc': cliente.ruc,
                'direccion': cliente.direccion,
                'localidad': cliente.localidad,
                'telefono': cliente.telefono,
                'pais': cliente.pais,
            }
            return JsonResponse(data)

    return JsonResponse({'error': 'Cliente no encontrado'}, status=404)


def buscar_item_v(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
        query = request.GET.get('term', '').strip()

        servicios = Servicios.objects.filter(nombre__icontains=query, tipogasto='V')[:10]

        results = [{'id': servicio.id, 'text': servicio.nombre} for servicio in servicios]
        return JsonResponse(results, safe=False)

    return JsonResponse({'error': 'Solicitud inválida'}, status=400)


def buscar_items_v(request):
    if request.method == "GET":
        servicio_id = request.GET.get("id")
        servicio = Servicios.objects.filter(id=int(servicio_id or 0)).first()

        if servicio:
            iva_texto = "Exento" if servicio.tasa == "X" else "Básico" if servicio.tasa == "B" else "Desconocido"
            embarque_texto = "Pendiente" if servicio.imputar == "S" else "No imputar" if servicio.imputar == "N" else "Desconocido"

            data = {
                'item': servicio.codigo,
                'nombre': servicio.nombre,
                'iva': iva_texto,
                'cuenta': servicio.contable,
                'embarque': embarque_texto,
                'comp': servicio.activa,
                'gasto': servicio.modo,
                'imputar': servicio.imputar
            }
            return JsonResponse(data)

    return JsonResponse({'error': 'Servicio no encontrado'}, status=404)

def buscar_items_v_codigo(request):
    if request.method == "GET":
        servicio_id = request.GET.get("id")
        servicio = Servicios.objects.filter(codigo=int(servicio_id or 0)).first()

        if servicio:
            iva_texto = "Exento" if servicio.tasa == "X" else "Básico" if servicio.tasa == "B" else "Desconocido"
            embarque_texto = "Pendiente" if servicio.imputar == "S" else "No imputar" if servicio.imputar == "N" else "Desconocido"

            data = {
                'item': servicio.codigo,
                'nombre': servicio.nombre,
                'iva': iva_texto,
                'cuenta': servicio.contable,
                'embarque': embarque_texto,
                'comp': servicio.activa,
                'gasto': servicio.modo,
                'imputar': servicio.imputar
            }
            return JsonResponse(data)

    return JsonResponse({'error': 'Servicio no encontrado'}, status=404)


def generar_autogenerado(tipo, hora, fecha, numero):
    fecha = fecha.replace('-', '')
    fecha_hora = fecha + hora
    tipo = tipo
    autogenerado = f"{fecha_hora}{tipo}{numero}"

    return autogenerado


def procesar_factura(request):
    try:
        with transaction.atomic():

            if request.method == 'POST':

                lista = Boleta.objects.last()
                numero = int(lista.numero) + 1
                hora = datetime.now().strftime('%H%M%S%f')
                fecha = request.POST.get('fecha')
                tipo = request.POST.get('tipoFac', 0)

                preventa = json.loads(request.POST.get('preventa'))
                registro_carga_raw = request.POST.get('registroCarga')
                registro_carga = json.loads(registro_carga_raw) if registro_carga_raw else {}
                autogenerado = generar_autogenerado(tipo, hora, fecha, numero)
                facturas_json = request.POST.get('facturas_imputadas')
                if facturas_json:
                    facturas_imputadas = json.loads(facturas_json)
                else:
                    facturas_imputadas = []
                if preventa:
                    numero_preventa=preventa.get('autogenerado')
                    master=preventa.get('master')
                    house=preventa.get('house')
                    posicion=preventa.get('posicion')
                    kilos=preventa.get('kilos')
                    bultos=preventa.get('bultos')
                    terminos=preventa.get('incoterms')
                    pagoflete=preventa.get('pago')
                    origen=preventa.get('origen')
                    destino=preventa.get('destino')
                    seguimiento=preventa.get('seguimiento')
                    referencia = None
                    aplicable = None
                    volumen = shipper=agente=detalle=None
                    transportista = llegasale=consignatario = commodity= None
                    vuelo = master=house=origen=destino=wr=None

                    reg=Factudif.objects.filter(znumero=numero_preventa)

                    for r in reg:
                        r.zfacturado='S'
                        r.save()

                else:
                    if registro_carga:
                        kilos = float(registro_carga.get('peso') or 0)
                        volumen = float(registro_carga.get('volumen') or 0)
                        bultos = int(registro_carga.get('bultos') or 0)
                        aplicable = float(registro_carga.get('aplicable')or 0)

                        seguimiento = registro_carga.get('seguimiento', '')
                        referencia = registro_carga.get('referencia', '')
                        transportista = registro_carga.get('transportista_nro', '')
                        vuelo = registro_carga.get('vuelo_vapor', '')
                        master = registro_carga.get('mawb', '')
                        house = registro_carga.get('hawb', '')
                        origen = registro_carga.get('origen', '')
                        destino = registro_carga.get('destino', '')
                        llegasale = registro_carga.get('fecha_llegada_salida', None)
                        consignatario = registro_carga.get('consignatario_nro', '')
                        commodity = registro_carga.get('commodity', '')
                        wr = registro_carga.get('wr', '')
                        shipper = registro_carga.get('shipper_nro', '')
                        terminos = registro_carga.get('incoterms', '')
                        pagoflete = 'C' if registro_carga.get('pago', '') == 'COLLECT' else 'P'  if registro_carga.get('pago', '')=='PREPAID' else ''
                        agente = registro_carga.get('agente_nro', '')
                        posicion = registro_carga.get('posicion', '')
                        detalle = registro_carga.get('observaciones', '')
                    else:
                        kilos = None
                        volumen = None
                        bultos = None
                        aplicable = None

                        seguimiento = None
                        referencia = None
                        transportista = None
                        vuelo = None
                        master = None
                        house = None
                        origen = None
                        destino = None
                        llegasale = None
                        consignatario = None
                        commodity = None
                        wr = None
                        shipper = None
                        terminos = None
                        pagoflete = None
                        agente = None
                        posicion = None
                        detalle = None

                serie = request.POST.get('serie', "")
                prefijo = request.POST.get('prefijo', 0)
                moneda = request.POST.get('moneda', "")
                arbitraje = request.POST.get('arbitraje', 0)
                paridad = request.POST.get('paridad', 0)
                cliente_data = json.loads(request.POST.get('clienteData'))
                codigo_cliente = cliente_data['codigo']
                cliente = Clientes.objects.get(codigo=codigo_cliente)
                fecha_obj = datetime.strptime(fecha, '%Y-%m-%d')

                precio_total = request.POST.get('total', 0)
                neto = request.POST.get('neto', 0)
                iva = request.POST.get('iva', 0)

                items_data = json.loads(request.POST.get('items')) #llega mal el codigo del item

                tipo_mov = tipo
                tipo_asiento = 'V'
                detalle1 = 'S/I'
                detalle_mov = detalle  if registro_carga else 'S/I'
                nombre_mov = ""
                asiento = generar_numero()
                movimiento_num = modificar_numero(asiento)

                if int(tipo) == 23:
                    detalle1 = 'e-NOT/CRED'
                    nombre_mov = 'NOTACONTCRE'
                elif int(tipo) == 24:
                    detalle1 = 'e-VTA/CRED'
                    tipo_asiento = 'V'
                    nombre_mov = 'BOLETA'
                elif int(tipo) == 11:
                    detalle1 = 'DEV/CTDO'
                    nombre_mov = 'DEVOLUCION'
                elif int(tipo) == 21:
                    detalle1 = 'NOT/CRED'
                    tipo_asiento = 'V'
                    nombre_mov = 'NOTA CRED.'
                elif int(tipo) == 22:
                    detalle1 = 'NOT/DEB'
                    tipo_asiento = 'V'
                    nombre_mov = 'NOTA DEB.'
                elif int(tipo) == 20:
                    detalle1 = 'VTA/CRED'
                    tipo_asiento = 'V'
                    nombre_mov = 'FACTURA'

                if int(tipo)==21 and facturas_imputadas or int(tipo)==23 and facturas_imputadas:
                    for fac_i in facturas_imputadas:
                        fac = Movims.objects.filter(mautogen=fac_i.get('autogenerado')).first()

                        if int(tipo)==21 and fac.mtipo!=20:
                            return JsonResponse({
                                "success": False,
                                "mensaje": {'mensaje':'Seleccionó un E-ticket, debe seleccionar una factura para imputar esta Nota Credito.'},
                            })

                        if int(tipo)==23 and fac.mtipo!=24:
                            return JsonResponse({
                                "success": False,
                                "mensaje": {'mensaje':'Seleccionó una Factura, debe seleccionar un E-ticket para imputar esta N/C E-ticket'},
                            })

                        impuc = Impuvtas()
                        impuc.autogen = str(autogenerado)
                        impuc.cliente = codigo_cliente
                        impuc.monto = fac_i.get('monto_imputado')
                        impuc.autofac = fac_i.get('autogenerado')
                        impuc.save()

                        fac.msaldo = (float(fac.msaldo) if fac.msaldo else 0) - float(fac_i.get('monto_imputado'))
                        fac.save()

               # detalle_asiento = detalle1 + serie + str(prefijo) + str(numero) + cliente.empresa
                detalle_asiento = detalle1 + '-' + serie + '-' + str(prefijo) + '-' + str(numero) + '-' + cliente.empresa


                movimiento = {
                    'tipo': tipo_mov,
                    'fecha': fecha_obj,
                    'boleta': numero,
                    'monto': neto,
                    'iva': iva,
                    'total': precio_total,
                    'saldo': precio_total,
                    'moneda': moneda,
                    'detalle': detalle_mov,
                    'cliente': cliente.codigo,
                    'nombre': cliente.empresa,
                    'nombremov': nombre_mov,
                    'cambio': arbitraje,
                    'autogenerado': autogenerado,
                    'serie': serie,
                    'prefijo': prefijo,
                    'posicion': posicion,
                    'anio': fecha_obj.year,
                    'mes': fecha_obj.month,
                    'monedaoriginal': moneda,
                    'montooriginal': precio_total,
                    'arbitraje': arbitraje,
                }
                asiento_general = {
                    'detalle': detalle_asiento,
                    'asiento': asiento,
                    'monto': precio_total,
                    'moneda': moneda,
                    'cambio': arbitraje,
                    'conciliado': 'N',
                    'clearing': fecha_obj,
                    'fecha': fecha_obj,
                    'imputacion': 1,
                    'tipo': tipo_asiento,
                    'cuenta': cliente.ctavta,
                    'documento': str(numero),
                    'vencimiento': fecha_obj,
                    'pasado': 0,
                    'autogenerado': autogenerado,
                    'cliente': cliente.codigo,
                    'banco': 'S/I',
                    'centro': 'S/I',
                    'mov': movimiento_num,
                    'anio': fecha_obj.year,
                    'mes': fecha_obj.month,
                    'fechacheque': fecha_obj,
                    'paridad': paridad,
                    'posicion': 'S/I',
                    'nroserv':None
                }
                crear_movimiento(movimiento)
                crear_asiento(asiento_general)
                mnt_neto_iva_basica = 0
                exento = 0
                for item_data in items_data:
                    aux = int(movimiento_num) + 1
                    precio = float(item_data.get('precio'))
                    coniva = 0
                    totaliva = 0
                    if item_data.get('iva') == 'Basico' or item_data.get('iva') == 'Básico':
                        mnt_neto_iva_basica+=precio
                        coniva = precio * 1.22
                        totaliva = precio * 0.22
                    else:
                        exento+=precio
                        coniva = precio
                        totaliva = 0

                    boleta = Boleta()
                    numero = numero
                    boleta.autogenerado = autogenerado
                    boleta.tipo = tipo
                    boleta.fecha = fecha
                    boleta.vto = fecha
                    boleta.tipofactura = serie
                    boleta.serie = serie
                    boleta.prefijo = prefijo
                    boleta.numero = numero
                    boleta.nrocliente = cliente.codigo
                    boleta.cliente = cliente.empresa
                    boleta.direccion = cliente.direccion
                    boleta.direccion2 = cliente.direccion2
                    boleta.localidad = cliente.localidad
                    boleta.ciudad = cliente.ciudad
                    boleta.pais = cliente.pais
                    boleta.telefax = cliente.telefono
                    boleta.ruc = cliente.ruc
                    boleta.condiciones = 'S/I'
                    boleta.corporativo = 'S/I'
                    boleta.moneda = moneda
                    boleta.cambio = arbitraje
                    boleta.paridad = paridad
                    boleta.tipocliente = 'RESPONSABLE INSCRIPTO'
                    boleta.nroservicio = item_data.get('id')
                    boleta.concepto = item_data.get('descripcion')
                    boleta.precio = item_data.get('precio')
                    boleta.iva = item_data.get('iva')
                    boleta.cuenta = item_data.get('cuenta')
                    boleta.monto = item_data.get('precio')
                    boleta.totiva = totaliva
                    boleta.total = coniva
                    boleta.master=master
                    boleta.house=house
                    boleta.posicion=posicion
                    boleta.kilos=kilos
                    boleta.bultos=bultos
                    boleta.terminos=terminos
                    boleta.pagoflete=pagoflete
                    boleta.origen=origen
                    boleta.destino=destino
                    boleta.seguimiento=seguimiento
                    boleta.refer=referencia
                    boleta.aplicable=aplicable
                    boleta.vuelo=vuelo
                    boleta.volumen=volumen
                    boleta.detalle=detalle
                    boleta.commodity=commodity
                    boleta.consignatario=consignatario
                    boleta.agente=agente
                    boleta.llegasale=llegasale
                    boleta.carrier=transportista
                    boleta.wr=wr
                    boleta.save()

                    asiento_vector = {
                        'detalle': detalle_asiento,
                        'monto': item_data.get('precio'),
                        'moneda': moneda,
                        'cambio': arbitraje,
                        'asiento': asiento,
                        'conciliado': 'N',
                        'clearing': fecha_obj,
                        'fecha': fecha_obj,
                        'imputacion': 2,
                        'tipo': tipo_asiento,
                        'cuenta': item_data.get('cuenta'),
                        'documento': str(numero),
                        'vencimiento': fecha_obj,
                        'pasado': 0,
                        'autogenerado': autogenerado,
                        'cliente': cliente.codigo,
                        'banco': 'S/I',
                        'centro': 'S/I',
                        'mov': aux,
                        'anio': fecha_obj.year,
                        'mes': fecha_obj.month,
                        'fechacheque': fecha_obj,
                        'paridad': paridad,
                        'nroserv':item_data.get('id'),
                        'posicion':posicion
                    }
                    crear_asiento(asiento_vector)
                    movimiento_num = aux

                    if preventa:
                        gastos_detalle_marcar(preventa.get('autogenerado'),autogenerado)

                resultado = facturar_uruware(
                    numero, tipo, serie, moneda, cliente_data,
                    precio_total, neto, iva, items_data, facturas_imputadas, fecha_obj,arbitraje,mnt_neto_iva_basica,exento,autogenerado
                )

                if resultado["success"]:
                    return JsonResponse({
                        "success": True,
                        "mensaje": resultado["mensaje"],
                        "ucfe_response": resultado.get("ucfe_response", {}),
                    })
                else:
                    return JsonResponse({
                        "success": False,
                        "mensaje": resultado["mensaje"],
                    })
            return None
    except Exception as e:
        return JsonResponse({'status': 'Error: ' + str(e)})


def gastos_detalle_marcar(numero_preventa,autogenerado):
    try:
        if not numero_preventa or not autogenerado:
            raise TypeError('Numero o autogenerado invalido.')


        reg = Factudif.objects.filter(znumero=numero_preventa)

        if not reg:
            raise TypeError('Preventa no encontrada.')

        clase = reg[0].zclase
        embarque = reg[0].zrefer

        gastos = VistaGastosPreventa.objects.filter(
            numero=embarque,
            source=clase,
        ).filter(
                Q(detalle__isnull=True) | Q(detalle='S/I') | Q(detalle='')
            )

        ids_coincidentes = []

        for r in reg:
            num_servicio = r.zitem
            monto_gasto = Decimal(r.zmonto)

            for g in gastos:
                precio = Decimal(g.precio or 0)
                costo = Decimal(g.costo or 0)

                if g.id_servicio == num_servicio and (precio == monto_gasto or costo == monto_gasto):
                    ids_coincidentes.append(g.id)

        if clase == "IM":
            service = Serviceaereo.objects.filter(id__in=ids_coincidentes)
        elif clase == "EM":
            service = ExpmaritServiceaereo.objects.filter(id__in=ids_coincidentes)
        elif clase == "IA":
            service = ImportServiceaereo.objects.filter(id__in=ids_coincidentes)
        elif clase == "EA":
            service = ExportServiceaereo.objects.filter(id__in=ids_coincidentes)
        elif clase == "IT":
            service = ImpterraServiceaereo.objects.filter(id__in=ids_coincidentes)
        elif clase == "ET":
            service = ExpterraServiceaereo.objects.filter(id__in=ids_coincidentes)
        else:
            raise TypeError('Clase invalida.')

        if not service:
            raise TypeError('Ocurrió un problema al buscar los gastos asociados.')

        for s in service:
            s.detalle=autogenerado
            s.save()

    except Exception as e:
        pass

def generar_numero():
    # Obtener la fecha y hora actual
    ahora = datetime.now()

    # Tomar los dos últimos dígitos del año
    año = str(ahora.year)[-2:]

    # Mes, día, hora, minutos y segundos
    mes = f"{ahora.month:02}"
    dia = f"{ahora.day:02}"
    hora = f"{ahora.hour:02}"
    minutos = f"{ahora.minute:02}"
    segundos = f"{ahora.second:02}"

    # Concatenar para formar el número (ejemplo: 11051019041186)
    numero = f"{año}{mes}{dia}{hora}{minutos}{segundos}"

    return numero

def modificar_numero(numero):
    # Quitar el primer dígito y los últimos dos dígitos
    numero_modificado = numero[1:-2]
    return numero_modificado


def crear_asiento(asiento):
    try:
        lista = Asientos()
        id = lista.get_id()
        lista.id = lista.get_id()
        lista.fecha = asiento['fecha']
        lista.asiento = asiento['asiento']
        lista.cuenta = asiento['cuenta']
        lista.imputacion = asiento['imputacion']
        lista.tipo = asiento['tipo']
        lista.documento = asiento['documento']
        lista.vto = asiento['vencimiento']
        lista.pasado = asiento['pasado']
        lista.autogenerado = asiento['autogenerado']
        lista.cliente = asiento['cliente']
        lista.banco = asiento['banco']
        lista.centro = asiento['centro']
        lista.mov = asiento['mov']
        lista.anoimpu = asiento['anio']
        lista.mesimpu = asiento['mes']
        lista.fechacheque = asiento['fechacheque']
        lista.paridad = asiento['paridad']
        lista.monto = asiento['monto']
        lista.detalle = asiento['detalle']
        lista.cambio = asiento['cambio']
        lista.moneda = asiento['moneda']
        lista.nroserv = asiento['nroserv']
        lista.posicion = asiento['posicion']
        lista.save()

    except Exception as e:
        raise


def crear_movimiento(movimiento):
    try:
        lista = Movims()
        lista.id = lista.get_id()
        lista.mtipo = movimiento['tipo']
        lista.mfechamov = movimiento['fecha']
        lista.mboleta = movimiento['boleta']
        lista.mmonto = movimiento['monto']
        lista.miva = movimiento['iva']
        lista.mtotal = movimiento['total']
        lista.msobretasa = 0
        lista.msaldo = movimiento['saldo']
        lista.mvtomov = movimiento['fecha']
        lista.mmoneda = movimiento['moneda']
        lista.mdetalle = movimiento['detalle']
        lista.mcliente = movimiento['cliente']
        lista.mnombre = movimiento['nombre']
        lista.mnombremov = movimiento['nombremov']
        lista.mcambio = movimiento['cambio']
        lista.mautogen = movimiento['autogenerado']
        lista.mserie = movimiento['serie']
        lista.mprefijo = movimiento['prefijo']
        lista.mposicion = movimiento['posicion']
        lista.mmesimpu = movimiento['mes']
        lista.manoimpu = movimiento['anio']
        lista.mmonedaoriginal = movimiento['monedaoriginal']
        lista.marbitraje = movimiento['arbitraje']
        lista.mmontooriginal = movimiento['montooriginal']
        lista.mactivo = 'S'
        lista.save()

    except Exception as e:
        raise


def source_infofactura(request):
    try:
        registros = VPreventas.objects.all()

        data = [{
            'numero': item.znumero,
            'cliente': item.zconsignatario,
            'posicion': item.zposicion,
            'master': item.zmaster,
            'house': item.zhouse,
            'vapor_vuelo': item.zcarrier,
            'contenedor': (
                Envases.objects.filter(numero=item.zrefer).order_by('id').first().nrocontenedor
                if Envases.objects.filter(numero=item.zrefer).exists() else 0
            ),
            'clase': item.zclase,
            'referencia': item.zrefer,
            'fecha': item.zllegasale.strftime('%Y-%m-%d') if item.zllegasale else None,
        } for item in registros]

        return JsonResponse({'data': data})

    except Exception as e:
        return JsonResponse({'error': str(e)})



def source_infofactura_cliente(request):
    try:
        start = int(request.GET.get('start', 0))
        length = int(request.GET.get('length', 5))
        cliente = str(request.GET.get('cliente'))

        registros = VPreventas.objects.filter(zconsignatario=cliente)

        total_registros = len(registros)

        # Paginación
        registros_paginated = registros[start:start + length]

        # Construir los datos para la tabla
        data = [{
            'numero': item.znumero,
            'consignatario': item.zconsignatario,
            'posicion': item.zposicion,
            'master': item.zmaster,
            'house': item.zhouse,
            'vapor_vuelo': item.zcarrier,
            'contenedor': (
                Envases.objects.filter(numero=item.zrefer).order_by('id').first().nrocontenedor
                if Envases.objects.filter(numero=item.zrefer).exists() else 0
            ),
            'clase': item.zclase,
            'referencia': item.zrefer,
            'sale_llega': item.zllegasale.strftime('%Y-%m-%d') if item.zllegasale else None,
        } for item in registros_paginated]
        # Respuesta JSON
        return JsonResponse({
            'draw': int(request.GET.get('draw', 1)),
            'recordsTotal': total_registros,
            'recordsFiltered': total_registros,
            'data': data,
        })


    except Exception as e:
        return JsonResponse({'error': str(e)})

def cargar_preventa_infofactura(request):
    if request.method == 'POST':
        clase = request.POST.get('clase')
        referencia = int(request.POST.get('referencia'))
        preventa = int(request.POST.get('preventa'))
        gastos_data_list = []
        total_sin_iva = Decimal('0.00')
        total_con_iva = Decimal('0.00')

        start = int(request.GET.get('start', 0))
        length = int(request.GET.get('length', 10))

        operativas = {
            'IM':'importacion_maritima',
            'IA':'importacion_aerea',
            'IT':'importacion_terrestre',
            'EM':'exportacion_maritima',
            'EA':'exportacion_aerea',
            'ET':'exportacion_terrestre',
        }

        modelo_operativa = {
            'IM': Embarqueaereo,
            'IA': ImportEmbarqueaereo,
            'IT': ImpterraEmbarqueaereo,
            'EM': ExpmaritEmbarqueaereo,
            'EA': ExportEmbarqueaereo,
            'ET': ExpterraEmbarqueaereo
        }
        modelo_reserva = {
            'IM': Reservas,
            'IA': ImportReservas,
            'IT': ImpterraReservas,
            'EM': ExpmaritReservas,
            'EA': ExportReservas,
            'ET': ExpterraReservas
        }

        modulo = operativas[clase]
        modelo = modelo_operativa[clase]
        modelo_r= modelo_reserva[clase]
        embarque = modelo.objects.filter(numero=referencia).first() if modelo else None

        if embarque:
            posicion = embarque.posicion

        if posicion:
            reserva= modelo_r.objects.filter(posicion=posicion).first() if modelo_r else None
            numero_reserva=reserva.numero if reserva else None

        bloqueo_info = verificar_bloqueo_edicion(referencia, numero_reserva, modulo, request.user)

        try:
            prev = VPreventas.objects.get(znumero=preventa)

            # gastos_raw = VistaGastosPreventa.objects.filter(numero=referencia,source=clase)

            gastos_raw = VistaGastosPreventa.objects.filter(
                numero=referencia,
                source=clase
            ).filter(
                Q(detalle__isnull=True) | Q(detalle='') | Q(detalle='S/I')
            )

            reg = Factudif.objects.filter(znumero=preventa)

            ids_coincidentes = []

            #encontrar los que se facturaron

            for r in reg:
                num_servicio = r.zitem
                monto_gasto = Decimal(r.zmonto)

                for g in gastos_raw:
                    precio = Decimal(g.precio or 0)
                    costo = Decimal(g.costo or 0)

                    if g.id_servicio == num_servicio and (precio == monto_gasto or costo == monto_gasto):
                        ids_coincidentes.append(g.id)

            gastos = VistaGastosPreventa.objects.filter(id__in=ids_coincidentes,source=prev.zclase)

            total_gastos = gastos.count()
            gastos_paginated = gastos[start:start + length]

            if total_gastos > 0:
                for gasto in gastos_paginated:
                    valor = gasto.precio if gasto.precio and gasto.precio !=0 else gasto.costo if gasto.costo and gasto.costo!=0 else 0

                    gasto_data = {
                        'descripcion': gasto.servicio,
                        'total': float(valor),
                        'iva': gasto.iva,
                        'original': float(gasto.pinformar or 0),
                        'moneda': gasto.moneda,
                        'posicion': prev.zposicion,
                        'cuenta': gasto.cuenta,
                        'codigo': gasto.id_servicio,
                    }

                    total_sin_iva += valor

                    if gasto.iva == 'Basico' or gasto.iva == 'Básico':
                        total_con_iva += valor * Decimal('1.22')
                    else:
                        total_con_iva += valor

                    gastos_data_list.append(gasto_data)

            ref = prev.zrefer
            try:
                if clase == "IM":
                    embarque = Embarqueaereo.objects.get(numero=ref)
                    moneda = Monedas.objects.get(codigo=embarque.moneda).nombre
                elif clase == "IA":
                    embarque = ImportEmbarqueaereo.objects.get(numero=ref)
                    moneda = embarque.moneda
                elif clase == "EA":
                    embarque = ExportEmbarqueaereo.objects.get(numero=ref)
                    moneda = embarque.moneda
                elif clase == "EM":
                    embarque = ExpmaritEmbarqueaereo.objects.get(numero=ref)
                    moneda = embarque.moneda
                elif clase == "IT":
                    embarque = ImpterraEmbarqueaereo.objects.get(numero=ref)
                    moneda = embarque.moneda
                elif clase == "ET":
                    embarque = ExpterraEmbarqueaereo.objects.get(numero=ref)
                    moneda = embarque.moneda

            except Embarqueaereo.DoesNotExist:
                embarque=None
                moneda = None

            cliente = Clientes.objects.get(codigo=prev.zcliente)

            llegada_salida = (
                prev.zllegasale.strftime('%Y-%m-%d') if prev.zllegasale else None
            )

            data_preventa = {
                'autogenerado':prev.znumero,
                'house':prev.zhouse,
                'master':prev.zmaster,
                'moneda': moneda if moneda else None,
                'total_con_iva': str(total_con_iva),
                'total_sin_iva': str(total_sin_iva),
                'cliente_i': cliente.empresa if cliente else None,
                'nrocliente': cliente.codigo if cliente else None,
                'peso': prev.zkilos,
                'direccion': cliente.direccion if cliente else None,
                'localidad': cliente.localidad if cliente else None,
                'bultos': prev.zbultos,
                'volumen': prev.zvolumen,
                'commodity': prev.zcommodity,
                'inconterms': prev.zterminos,
                'flete': prev.zpagoflete,
                'deposito': "S/I",
                'wr': prev.zwr,
                'referencia': prev.zrefer,
                'llegada_salida': llegada_salida,
                'origen': prev.zorigen,
                'destino': prev.zdestino,
                'transportista': prev.zcarrier,
                'consignatario': prev.zconsignatario,
                'embarcador': prev.zembarcador,
                'agente': prev.zagente,
                'vuelo_vapor': prev.zcarrier,
                'seguimiento': prev.zseguimiento,
                'mawb_mbl_mcrt': prev.zmaster,
                'hawb_hbl_hcrt': prev.zhouse,
                'posicion': prev.zposicion,
                'status': 'PARA FACTURAR',
                'orden': "S/I",
                'modo': prev.ztransporte,
            }

            data = {
                "draw": int(request.GET.get('draw', 1)),
                "recordsTotal": total_gastos,
                "recordsFiltered": total_gastos,
                "data": gastos_data_list,
                "data_preventa": data_preventa,
            }

            if bloqueo_info:
                data['bloqueo'] = bloqueo_info

            return JsonResponse(data, safe=False)

        except VPreventas.DoesNotExist:
            return JsonResponse({'error': 'Infofactura no encontrada'}, safe=False)
        except Clientes.DoesNotExist:
            return JsonResponse({'error': 'Cliente no encontrado'}, safe=False)
    return None


def verificar_bloqueo_edicion(referencia, numero_reserva, modulo, usuario):
    """
    Verifica si la referencia o su madre están bloqueadas por otro usuario.
    Retorna un diccionario con el mensaje de bloqueo o None si no hay bloqueo.
    """
    for ref in [numero_reserva, referencia]:
        if not ref:
            continue
        bloqueo = BloqueoEdicion.objects.filter(
            referencia=ref,
            fecha_expiracion__gt=now(),
            activo=True,
            modulo=modulo
        ).first()

        if bloqueo:
            tiempo_restante = bloqueo.fecha_expiracion - now()
            minutos = int(tiempo_restante.total_seconds() // 60)
            segundos = int(tiempo_restante.total_seconds() % 60)
            return {
                'bloqueado': True,
                'usuario': bloqueo.usuario.username,
                'mensaje': f'El embarque asociado a esta preventa está siendo editado por {bloqueo.usuario.username}. '
                           f'Podrás facturar en aproximadamente {minutos} min {segundos} seg.'
            }
    return None


def cargar_preventa_infofactura_multiple(request):
    if request.method == 'POST':
        try:
            seleccionados = json.loads(request.POST.get('seleccionados', '[]'))

            resultado = []

            for item in seleccionados:
                preventa = item.get('numero')
                referencia = item.get('referencia')
                clase = item.get('clase')

                gastos_data_list = []
                total_sin_iva = Decimal('0.00')
                total_con_iva = Decimal('0.00')

                try:
                    prev = VPreventas.objects.get(znumero=preventa)
                    gastos = VistaGastosPreventa.objects.filter(numero=referencia)

                    llegada_salida = (
                        prev.zllegasale.strftime('%Y-%m-%d') if prev.zllegasale else None
                    )

                    total_gastos = gastos.count()

                    for gasto in gastos:
                        gasto_data = {
                            'descripcion': gasto.servicio,
                            'total': float(gasto.precio),
                            'iva': gasto.iva,
                            'original': float(gasto.pinformar),
                            'moneda': gasto.moneda,
                        }
                        total_sin_iva += gasto.precio
                        if gasto.iva == 'Basico' or gasto.iva == 'Básico':
                            total_con_iva += gasto.precio * Decimal('1.22')
                        else:
                            total_con_iva += gasto.precio

                        gastos_data_list.append(gasto_data)

                    ref = prev.zrefer

                    if clase == "IM":
                        embarque = Embarqueaereo.objects.get(numero=ref)
                        cliente = Clientes.objects.get(codigo=embarque.cliente)
                        moneda = Monedas.objects.get(codigo=embarque.moneda).nombre
                    elif clase == "IA":
                        embarque = ImportEmbarqueaereo.objects.get(numero=ref)
                        cliente = Clientes.objects.get(codigo=embarque.cliente)
                        moneda = embarque.moneda
                    elif clase == "EA":
                        embarque = ExportEmbarqueaereo.objects.get(numero=ref)
                        cliente = Clientes.objects.get(codigo=embarque.cliente)
                        moneda = embarque.moneda
                    elif clase == "EM":
                        embarque = ExpmaritEmbarqueaereo.objects.get(numero=ref)
                        cliente = Clientes.objects.get(codigo=embarque.cliente)
                        moneda = embarque.moneda
                    elif clase == "IT":
                        embarque = ImpterraEmbarqueaereo.objects.get(numero=ref)
                        cliente = Clientes.objects.get(codigo=embarque.cliente)
                        moneda = embarque.moneda
                    elif clase == "ET":
                        embarque = ExpterraEmbarqueaereo.objects.get(numero=ref)
                        cliente = Clientes.objects.get(codigo=embarque.cliente)
                        moneda = embarque.moneda


                    data_preventa_old = {
                        'autogenerado': prev.autogenerado,
                        'house': prev.house,
                        'master': prev.master,
                        'moneda': moneda,
                        'total_con_iva': str(total_con_iva),
                        'total_sin_iva': str(total_sin_iva),
                        'cliente_i': cliente.empresa,
                        'peso': prev.kilos,
                        'direccion': cliente.direccion,
                        'localidad': cliente.localidad,
                        'aplic': Cargaaerea.objects.filter(numero=ref).values('aplicable').first().get('aplicable', 'S/I') if clase == "IA" else 'S/I',
                        'bultos': prev.bultos,
                        'volumen': prev.volumen,
                        'commodity': prev.commodity,
                        'inconterms': prev.terminos,
                        'flete': prev.pagoflete,
                        'deposito': "S/I",
                        'wr': prev.wr,
                        'referencia': prev.referencia,
                        'llegada_salida': embarque.fecharetiro,
                        'origen': prev.destino,
                        'destino': prev.origen,
                        'transportista': prev.transportista,
                        'consignatario': prev.consigna,
                        'embarcador': prev.embarca,
                        'agente': prev.agente,
                        'vuelo_vapor': prev.vuelo,
                        'seguimiento': prev.seguimiento,
                        'mawb_mbl_mcrt': prev.master,
                        'hawb_hbl_hcrt': prev.house,
                        'posicion': prev.posicion,
                        'status': 'PARA FACTURAR',
                        'orden': "S/I",
                        'modo': 'MARITIMO',
                    }
                    data_preventa = {
                        'autogenerado': prev.znumero,
                        'house': prev.zhouse,
                        'master': prev.zmaster,
                        'moneda': moneda if moneda else None,
                        'total_con_iva': str(total_con_iva),
                        'total_sin_iva': str(total_sin_iva),
                        'cliente_i': cliente.empresa if cliente else None,
                        'peso': prev.zkilos,
                        'direccion': cliente.direccion if cliente else None,
                        'localidad': cliente.localidad if cliente else None,
                        # 'aplic': 0 if int(ref)<0 else Cargaaerea.objects.filter(numero=ref).values('aplicable').first().get('aplicable','S/I') if clase == "IA" else 'S/I',
                        'bultos': prev.zbultos,
                        'volumen': prev.zvolumen,
                        'commodity': prev.zcommodity,
                        'inconterms': prev.zterminos,
                        'flete': prev.zpagoflete,
                        'deposito': "S/I",
                        'wr': prev.zwr,
                        'referencia': prev.zrefer,
                        'llegada_salida': llegada_salida,
                        'origen': prev.zorigen,
                        'destino': prev.zdestino,
                        'transportista': prev.zcarrier,
                        'consignatario': prev.zconsignatario,
                        'embarcador': prev.zembarcador,
                        'agente': prev.zagente,
                        'vuelo_vapor': prev.zcarrier,
                        'seguimiento': prev.zseguimiento,
                        'mawb_mbl_mcrt': prev.zmaster,
                        'hawb_hbl_hcrt': prev.zhouse,
                        'posicion': prev.zposicion,
                        'status': 'PARA FACTURAR',
                        'orden': "S/I",
                        'modo': prev.ztransporte,
                    }

                    resultado.append({
                        "numero": preventa,
                        "referencia": referencia,
                        "clase": clase,
                        "gastos": gastos_data_list,
                        "data_preventa": data_preventa
                    })

                except Infofactura.DoesNotExist:
                    resultado.append({'error': f'Infofactura con número {preventa} no encontrada'})
                except Embarqueaereo.DoesNotExist:
                    resultado.append({'error': f'Embarque con referencia {referencia} no encontrado'})
                except Clientes.DoesNotExist:
                    resultado.append({'error': f'Cliente relacionado con referencia {referencia} no encontrado'})

            return JsonResponse({"data": resultado}, safe=False)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Error al procesar los datos enviados'}, safe=False)
        except Exception as e:
            return JsonResponse({'error': str(e)}, safe=False)

    return JsonResponse({'error': 'Método no permitido'}, status=405)


def guardar_arbitraje(request):
    if request.method == "POST":
        try:
            # Obtener datos del POST
            arb_dolar = request.POST.get('arbDolar', 0)
            par_dolar = request.POST.get('parDolar', 0)
            tipo_moneda = request.POST.get('tipoMoneda', 0)
            piz_dolar = request.POST.get('pizDolar', 0)
            ui = request.POST.get('ui', 0)
            fecha_cliente = request.POST.get('fecha', None)

            # Validar y formatear la fecha
            if fecha_cliente:
                fecha_cliente = datetime.strptime(fecha_cliente, '%Y-%m-%d')  # Convertir a datetime
            else:
                fecha_cliente = datetime.today()

            # Formatear la fecha con la hora actual
            fecha_final = fecha_cliente.replace(
                hour=datetime.now().hour,
                minute=datetime.now().minute,
                second=datetime.now().second,
                microsecond=datetime.now().microsecond
            )

            # Comprobar si ya existe un registro para la fecha
            registro_existente = Dolar.objects.filter(
                ufecha__date=fecha_final.date()
            ).first()

            if registro_existente:
                # Modificar el registro existente
                registro_existente.upizarra = float(piz_dolar)
                registro_existente.paridad = float(par_dolar)
                registro_existente.uvalor = float(arb_dolar)
                registro_existente.umoneda = float(tipo_moneda)
                registro_existente.ufecha = fecha_final
                registro_existente.ui = ui
                registro_existente.save()
            else:
                # Crear un nuevo registro
                dolar = Dolar()
                dolar.upizarra = float(piz_dolar)
                dolar.paridad = float(par_dolar)
                dolar.uvalor = float(arb_dolar)
                dolar.umoneda = float(tipo_moneda)
                dolar.ufecha = fecha_final
                dolar.ui = ui
                dolar.save()

            return JsonResponse({'status': 'Registro guardado correctamente.'})

        except Exception as e:
            return JsonResponse({'status': f'Error al guardar los datos: {str(e)}'}, status=500)

    else:
        return JsonResponse({'status': 'Método no permitido.'}, status=405)

"""
data_preventa = {
                'autogenerado':prev.autogenerado,
                'house':prev.house,
                'master':prev.master,
                'moneda': moneda if moneda else None,
                'total_con_iva': str(total_con_iva),
                'total_sin_iva': str(total_sin_iva),
                'cliente_i': cliente.empresa if cliente else None,
                'peso': prev.kilos,
                'direccion': cliente.direccion if cliente else None,
                'localidad': cliente.localidad if cliente else None,
                #'aplic': 0 if int(ref)<0 else Cargaaerea.objects.filter(numero=ref).values('aplicable').first().get('aplicable','S/I') if clase == "IA" else 'S/I',
                'bultos': prev.bultos,
                'volumen': prev.volumen,
                'commodity': prev.commodity,
                'inconterms': prev.terminos,
                'flete': prev.pagoflete,
                'deposito': "S/I",
                'wr': prev.wr,
                'referencia': prev.referencia,
                'llegada_salida': llegada_salida,
                'origen': prev.destino,
                'destino': prev.origen,
                'transportista': prev.transportista,
                'consignatario': prev.consigna,
                'embarcador': prev.embarca,
                'agente': prev.agente,
                'vuelo_vapor': prev.vuelo,
                'seguimiento': prev.seguimiento,
                'mawb_mbl_mcrt': prev.master,
                'hawb_hbl_hcrt': prev.house,
                'posicion': prev.posicion,
                'status': 'PARA FACTURAR',
                'orden': "S/I",
                'modo': 'MARITIMO',
            }

data = {
                "draw": int(request.GET.get('draw', 1)),
                "recordsTotal": total_gastos,
                "recordsFiltered": total_gastos,
                "data": gastos_data_list,
                "data_preventa": data_preventa,
            }
"""


def get_datos_embarque(request):
    posicion = request.POST.get("posicion")
    if not posicion or len(posicion) < 2:
        return JsonResponse({'success': False, 'error': 'Posición inválida'}, status=400)

    prefijo = posicion[:2]
    embarque = None
    embarqueReal = None
    reserva = None
    vuelo_vapor = None
    carga = None

    try:
        if prefijo == 'IM':
            embarque = IM.objects.filter(posicion=posicion).first()
            if not embarque:
                raise ValueError("Embarque no encontrado")
            reserva = Reservas.objects.filter(awb=embarque.awb).first()
            embarqueReal = Embarqueaereo.objects.filter(posicion=posicion).first()
            carga = Cargaaerea.objects.filter(numero=embarque.numero).values('producto__nombre','bultos').first()
            if embarque.vapor and isNumber(embarque.vapor):
                vuelo = Vapores.objects.filter(codigo=embarque.vapor).first()
                vuelo_vapor = vuelo.nombre if vuelo else None

        elif prefijo == 'IA':
            embarque = IA.objects.filter(posicion=posicion).first()
            if not embarque:
                raise ValueError("Embarque no encontrado")
            reserva = ImportReservas.objects.filter(awb=embarque.awb).first()
            embarqueReal = ImportEmbarqueaereo.objects.filter(posicion=posicion).first()
            carga = ImportCargaaerea.objects.filter(numero=embarque.numero).values('producto__nombre','bultos').first()
            conex = ImportConexaerea.objects.filter(numero=embarque.numero).values('ciavuelo', 'viaje').first()
            if conex:
                vuelo_vapor = str(conex['ciavuelo']) + str(conex['viaje'])

        elif prefijo == 'IT':
            embarque = IT.objects.filter(posicion=posicion).first()
            if not embarque:
                raise ValueError("Embarque no encontrado")
            reserva = ImpterraReservas.objects.filter(awb=embarque.awb).first()
            embarqueReal = ImpterraEmbarqueaereo.objects.filter(posicion=posicion).first()
            carga = ImpterraCargaaerea.objects.filter(numero=embarque.numero).values('producto__nombre','bultos').first()
            conex = ImportConexaerea.objects.filter(numero=embarque.numero).values('ciavuelo', 'viaje').first()
            if conex:
                vuelo_vapor = str(conex['ciavuelo']) + str(conex['viaje'])

        elif prefijo == 'EM':
            embarque = EM.objects.filter(posicion=posicion).first()
            if not embarque:
                raise ValueError("Embarque no encontrado")
            reserva = ExpmaritReservas.objects.filter(awb=embarque.awb).first()
            embarqueReal = ExpmaritEmbarqueaereo.objects.filter(posicion=posicion).first()
            carga = ExpmaritCargaaerea.objects.filter(numero=embarque.numero).values('producto__nombre','bultos').first()
            if embarque.vapor and isNumber(embarque.vapor):
                vuelo = Vapores.objects.filter(codigo=embarque.vapor).first()
                vuelo_vapor = vuelo.nombre if vuelo else None

        elif prefijo == 'EA':
            embarque = EA.objects.filter(posicion=posicion).first()
            if not embarque:
                raise ValueError("Embarque no encontrado")
            reserva = ExportReservas.objects.filter(awb=embarque.awb).first()
            embarqueReal = ExportEmbarqueaereo.objects.filter(posicion=posicion).first()
            carga = ExportCargaaerea.objects.filter(numero=embarque.numero).values('producto__nombre','bultos').first()
            conex = ImportConexaerea.objects.filter(numero=embarque.numero).values('ciavuelo', 'viaje').first()
            if conex:
                vuelo_vapor = str(conex['ciavuelo']) + str(conex['viaje'])

        elif prefijo == 'ET':
            embarque = ET.objects.filter(posicion=posicion).first()
            if not embarque:
                raise ValueError("Embarque no encontrado")
            reserva = ExpterraReservas.objects.filter(awb=embarque.awb).first()
            embarqueReal = ExpterraEmbarqueaereo.objects.filter(posicion=posicion).first()
            carga = ExpterraCargaaerea.objects.filter(numero=embarque.numero).values('producto__nombre','bultos').first()
            conex = ImportConexaerea.objects.filter(numero=embarque.numero).values('ciavuelo', 'viaje').first()
            if conex:
                vuelo_vapor = str(conex['ciavuelo']) + str(conex['viaje'])

        else:
            return JsonResponse({'success': False, 'error': 'Prefijo de posición no reconocido'}, status=400)

        peso = reserva.kilos if prefijo in ['EA','EM','ET'] else reserva.kilosmadre
        aplicable = reserva.aplicable if prefijo not in ['IT','ET','IM','EM'] else None
        volumen = reserva.volumen if prefijo not in ['IM','EM'] else None

        return JsonResponse({
            "referencia": embarque.numero,
            "seguimiento": embarque.seguimiento,
            "peso": peso,
            "aplicable": aplicable,
            "volumen": volumen,
            "transportista": embarque.transportista,
            "vuelo_vapor": vuelo_vapor,
            "mawb": embarque.awb,
            "hawb": embarque.hawb,
            "origen": embarque.origen,
            "destino": embarque.destino,
            "fecha_llegada_salida": embarque.fecha_embarque.strftime("%Y-%m-%d") if embarque.fecha_embarque else "",
            "consignatario": embarque.consignatario,
            "commodity": carga['producto__nombre'] if carga else "S/I",
            "bultos": carga['bultos'] if carga else "S/I",
            "wr": embarqueReal.wreceipt if embarqueReal else "",
            "shipper": embarque.embarcador,
            "incoterms": embarqueReal.terminos if embarqueReal else "",
            "pago": 'COLLECT' if embarque.pago_flete == 'C' else 'PREPAID' if embarque.pago_flete else 'S/I',
            "agente": embarque.agente,
            "posicion": embarque.posicion,
            "observaciones": 'S/I',
            "servicio": None,
            "transportista_nro": embarqueReal.transportista,
            "consignatario_nro": embarqueReal.consignatario,
            "agente_nro": embarqueReal.agente,
            "shipper_nro": embarqueReal.embarcador,
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_POST
def hacer_nota_credito_old(request):
    numero_nc = request.POST.get("numero")
    arbitraje = request.POST.get("arbitraje")
    autogenerado_factura = request.POST.get("autogenerado")

    if Movims.objects.filter(mboleta=numero_nc, mtipo=21).exists():
        return JsonResponse({"mensaje": "Ese número ya existe para una Nota de Crédito."}, status=400)

    try:
        with transaction.atomic():
            nuevos_movims = []
            nuevos_boleta = []
            nuevos_asientos = []

            hora = datetime.now().strftime('%H%M%S%f')
            fecha = datetime.now().strftime('%Y-%m-%d')

            nuevo_autogenerado = generar_autogenerado(21, hora, fecha, numero_nc)
            # Clonar BOLETA
            for bol in Boleta.objects.filter(autogenerado=autogenerado_factura):
                data = model_to_dict(bol)
                data.pop('id', None)
                data.update({
                    'autogenerado': nuevo_autogenerado,
                    'tipo': 21,
                    'numero': numero_nc,
                    'cambio': arbitraje,
                    'fecha': datetime.now(),
                    'vto': datetime.now(),
                })
                nuevos_boleta.append(Boleta(**data))
            # Clonar MOVIMS
            for mov in Movims.objects.filter(mautogen=autogenerado_factura):
                data = model_to_dict(mov)
                data.pop('id', None)
                data.update({
                    'mautogen': nuevo_autogenerado,
                    'mtipo': 21,
                    'mnombremov': 'NOTA CRED.',
                    'mboleta': numero_nc,
                    'marbitraje': arbitraje,
                    'mfechamov': datetime.now(),
                    'mvtomov': datetime.now(),
                    'mdetalle': f"Nota de credito de factura {mov.mboleta} - {mov.mnombre}",
                })
                nuevos_movims.append(Movims(**data))

            # Clonar ASIENTOS
            for asiento in Asientos.objects.filter(autogenerado=autogenerado_factura):
                data = model_to_dict(asiento)
                data.pop('id', None)

                data.update({
                    'autogenerado': nuevo_autogenerado,
                    'asiento': generar_numero(),
                    'detalle': f"NC-{asiento.detalle}",
                    'tipo': 'V',
                    'cambio': arbitraje,
                    'documento': numero_nc,
                    'fecha': datetime.now(),
                    'vto': datetime.now(),
                })
                nuevos_asientos.append(Asientos(**data))

            fac = Movims.objects.filter(mautogen=autogenerado_factura, mtipo=20).first()

            impuc = Impuvtas()
            impuc.autogen = str(nuevo_autogenerado)
            impuc.autofac = autogenerado_factura
            impuc.cliente = fac.mcliente
            impuc.monto = fac.mtotal
            impuc.save()

            fac.msaldo = 0
            fac.save()

            # Guardar clones
            Movims.objects.bulk_create(nuevos_movims)
            Boleta.objects.bulk_create(nuevos_boleta)
            Asientos.objects.bulk_create(nuevos_asientos)

        return JsonResponse({"mensaje": "Nota de crédito creada con éxito."})
    except Exception as e:
        return JsonResponse({"mensaje": f"Error al crear nota de crédito: {str(e)}"}, status=500)


def cargar_pendientes_imputacion_venta(request):
    try:
        nrocliente = request.GET.get('nrocliente')
        if not nrocliente:
            return JsonResponse({'error': 'Debe proporcionar un nrocliente'}, status=400)

        # Base: solo FACTURA, con saldo pendiente
        base = (VistaVentas.objects
                .filter(nrocliente=nrocliente, tipo__in=['FACTURA','E-TICKET'])
                .exclude(saldo=0))

        # Fila más reciente por autogenerado (desempate por pk)
        qs = (base
              .annotate(
                  rn=Window(
                      expression=RowNumber(),
                      partition_by=[F('autogenerado')],
                      order_by=[F('fecha').desc(), F('pk').desc()],
                  )
              )
              .filter(rn=1)
              .values('autogenerado', 'fecha', 'num_completo',
                      'total', 'saldo', 'tipo_cambio', 'detalle'))

        data = []
        for r in qs:
            fecha = r['fecha'].strftime('%Y-%m-%d') if r['fecha'] else ''
            data.append({
                'autogenerado': r['autogenerado'],
                'vto': fecha,                # si tenés otro campo de vencimiento, cámbialo aquí
                'emision': fecha,
                'num_completo': r['num_completo'] or '',
                'total': float(r['total'] or 0),
                'saldo': float(r['saldo'] or 0),
                'imputado': 0,
                'tipo_cambio': float(r['tipo_cambio'] or 0),
                'detalle': r['detalle'] or '',
            })

        return JsonResponse({'data': data}, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def facturar_uruware(numero,tipo,serie,moneda,cliente_data,precio_total,neto,iva,items_data,facturas_imputadas,fecha,arbitraje,mnto_neto,exento,autogen):
        try:
            numero = int(numero)

            tipo_cfe = None
            if int(tipo) == 23:
                # nc eticket
                tipo_cfe = 102
            elif int(tipo) == 24:
                # eticket
                tipo_cfe = 101
            elif int(tipo) == 21:
                # nc factura
                tipo_cfe = 112
            elif int(tipo) == 22:
                tipo_cfe = 112
            elif int(tipo) == 20:
                # efactura
                tipo_cfe = 111

            ui_valor = 0
            dolar_hoy = Dolar.objects.filter(ufecha__date=datetime.now()).first()
            if dolar_hoy:
                ui_valor = dolar_hoy.ui

            if arbitraje is None or arbitraje == 0:
                dolar_hoy = Dolar.objects.filter(ufecha__date=fecha).first()
                if dolar_hoy:
                    arbitraje = dolar_hoy.uvalor

            moneda = int(moneda)
            codigo_cliente = cliente_data['codigo']
            cliente = Clientes.objects.filter(codigo=codigo_cliente).first()
            ciudad = None
            if cliente:
                ciudad = Ciudades.objects.filter(codigo=cliente.ciudad).first()
            #
            if not ciudad:
                return JsonResponse({"success": False, "mensaje": "El cliente no tiene una ciudad ingresada. Dirijase a mantenimientos y complete los datos para facturar."})

            data = {
                "tipo_cfe": tipo_cfe,
                "serie": serie,
                "numero": numero,
                "fecha_emision": fecha.strftime('%Y-%m-%d'),
                "forma_pago": "2",
                "ruc_emisor": "213971080016",
                "razon_social": "Oceanlink LTDA",
                "codigo_sucursal": "1",
                "domicilio": "Bolonia 2280 LATU, Edificio Los Álamos, Of.103",
                "ciudad": "Montevideo",
                "departamento": "Montevideo",
                "moneda": "UYU" if moneda and moneda == 1 else "USD" if moneda and moneda == 2 else "EUR" if moneda and moneda == 3 else "Error",
                "neto_tasa_basica": mnto_neto,
                "iva_tasa_basica": "22" ,
                "iva_monto_basica": iva,
                "total": precio_total,
                "cantidad_items": len(items_data),
                "monto_pagar": precio_total,
                "monto_exento": Decimal(exento) if Decimal(exento) !=0 else '',
                "tipo_cambio": arbitraje,
                "hay_items_iva": False,
                "hay_items_exento": False,
                "tipo_doc_receptor": 2,
                "pais_codigo": "UY",
                "documento_receptor": cliente.ruc if cliente else '',
                "razon_social_receptor": cliente.razonsocial if cliente else '',
                "direccion_receptor": cliente.direccion if cliente else '',
                "ciudad_receptor": ciudad.nombre if ciudad else 'Montevideo',
                "pais_receptor": cliente.pais if cliente else '',
                "lleva_receptor": False,
            }

            if tipo in (23, 24):
                # Calcular tope en pesos
                tope_ui = Decimal("5000") * Decimal(ui_valor or 0)

                supera_tope = False
                if moneda == 1:  # pesos
                    supera_tope = Decimal(precio_total) > tope_ui
                elif moneda == 2:  # dólares
                    supera_tope = Decimal(precio_total) * Decimal(arbitraje or 0) > tope_ui

                if supera_tope:
                    # podés setear un flag en data
                    data["lleva_receptor"] = True
                else:
                    data["lleva_receptor"] = False

            data = {k: escape(str(v)) if isinstance(v, str) else v for k, v in data.items()}

            # data['exento'] = exento if exento else ''
            items = []
            for i, item in enumerate(items_data, start=1):

                if item.get('iva') == 'Basico' or item.get('iva')=='Básico':
                    data['hay_items_iva']=True
                else:
                    data['hay_items_exento']=True

                items.append({
                    "nro": i,
                    "ind_fact": 3 if item.get('iva') == 'Basico' or item.get('iva')=='Básico' else 1,
                    "nombre": escape(item.get("descripcion")),
                    "cantidad": 1,
                    "unidad": "N/A",
                    "precio_unitario": item.get("precio") ,
                    "monto": item.get("precio"),
                })

            referencias = []
            for i, fac in enumerate(facturas_imputadas, start=1):
                factura = Movims.objects.filter(mautogen=fac.get('autogenerado')).first()
                tipo_fac = 101 if factura.mtipo == 24  else 111 if factura.mtipo==20 else 'error'
                referencias.append({
                    "nro_linea": i,
                    "tipo_doc": tipo_fac,
                    "serie": factura.mserie if factura else '',
                    "numero_cfe": factura.mboleta if factura else '',
                    "fecha_cfe": factura.mfechamov.strftime('%Y-%m-%d') if factura else '' ,
                })
            # hacer el dict de las referencias cuando es nota d ecredito
            ucfe = UCFEClient(
                base_url="https://test.ucfe.com.uy/Inbox115/CfeService.svc",
                usuario="213971080016",
                rut="213971080016",
                clave="9rtcl5NzMXlRHKU2PGtPUw==",
                cod_comercio="OCEANL-394",
                cod_terminal="FC-394",
                wsdl_inbox="https://test.ucfe.com.uy/Inbox115/CfeService.svc?singleWsdl",
                wsdl_query="https://test.ucfe.com.uy/Query116/WebServicesFE.svc?singleWsdl"
            )
            if ucfe.is_folio_free(tipo_cfe, serie, numero, "213971080016"):
                xml = ucfe.render_xml(data, items,referencias)
                uuid_val = str(uuid.uuid4())

                resp_firma = ucfe.soap_solicitar_firma(
                    xml,
                    uuid_str=uuid_val,
                    rut_emisor="213971080016",
                    tipo_cfe=tipo_cfe,
                    serie=serie,
                    numero=numero
                )
                data_firma = serialize_object(resp_firma)
                cae_num = data_firma["Resp"].get("IdCae")
                boleta = Boleta.objects.filter(autogenerado=autogen)
                for b in boleta:
                    b.cae = cae_num
                    b.save()

                resp_post = ucfe.soap_obtener_cfe_emitido(
                    rut="213971080016",
                    tipo_cfe=tipo_cfe,
                    serie=serie,
                    numero=numero
                )
                data_post = serialize_object(resp_post)

                # ucfe.test_obtener_pdf("213971080016",tipo_cfe,serie,numero)

                if data_post:
                    return {
                        "success": True,
                        "mensaje": f"CFE {tipo_cfe}-{serie}-{numero} registrado",
                        "xml": xml,
                        "ucfe_response": data_post,
                    }
                else:
                    logging.info(f"Error al firmar: {data_firma} {xml}")
                    return {
                        "success": False,
                        "mensaje": f"Error al enviar a DGI {tipo_cfe}-{serie}-{numero}",
                        "xml": xml,
                    }
            else:
                return {"success": False, "mensaje": "Número de folio no disponible"}

        except Exception as e:
            logging.info(f"Error {e}")
            return {"success": False, "mensaje": str(e)}

@require_POST
def hacer_nota_credito(request):
    numero_nc = request.POST.get("numero")
    arbitraje = request.POST.get("arbitraje")
    autogenerado_factura = request.POST.get("autogenerado")

    fac = Movims.objects.filter(mautogen=autogenerado_factura).first()

    tipo = fac.mtipo

    tipo_nota = 21 if tipo == 20 else 23

    if Movims.objects.filter(mboleta=numero_nc, mtipo=tipo_nota).exists():
        return JsonResponse({"mensaje": "Ese número ya existe para una Nota de Crédito."}, status=400)

    try:
        with transaction.atomic():
            nuevos_movims = []
            nuevos_boleta = []
            nuevos_asientos = []

            hora = datetime.now().strftime('%H%M%S%f')
            fecha = datetime.now().strftime('%Y-%m-%d')

            nuevo_autogenerado = generar_autogenerado(tipo_nota, hora, fecha, numero_nc)
            # Clonar BOLETA
            for bol in Boleta.objects.filter(autogenerado=autogenerado_factura):
                data = model_to_dict(bol)
                data.pop('id', None)
                data.update({
                    'autogenerado': nuevo_autogenerado,
                    'tipo': tipo_nota,
                    'numero': numero_nc,
                    'cambio': arbitraje,
                    'fecha': datetime.now(),
                    'vto': datetime.now(),
                })
                nuevos_boleta.append(Boleta(**data))
            # Clonar MOVIMS
            for mov in Movims.objects.filter(mautogen=autogenerado_factura):
                data = model_to_dict(mov)
                data.pop('id', None)
                data.update({
                    'mautogen': nuevo_autogenerado,
                    'mtipo': tipo_nota,
                    'mnombremov': 'NOTA CRED.',
                    'mboleta': numero_nc,
                    'marbitraje': arbitraje,
                    'mfechamov': datetime.now(),
                    'mvtomov': datetime.now(),
                    'mdetalle': f"Nota de credito de factura {mov.mboleta} - {mov.mnombre}",
                })
                nuevos_movims.append(Movims(**data))

            # Clonar ASIENTOS
            for asiento in Asientos.objects.filter(autogenerado=autogenerado_factura):
                data = model_to_dict(asiento)
                data.pop('id', None)

                data.update({
                    'autogenerado': nuevo_autogenerado,
                    'asiento': generar_numero(),
                    'detalle': f"NC-{asiento.detalle}",
                    'tipo': 'V',
                    'cambio': arbitraje,
                    'documento': numero_nc,
                    'fecha': datetime.now(),
                    'vto': datetime.now(),
                })
                nuevos_asientos.append(Asientos(**data))

            impuc = Impuvtas()
            impuc.autogen = str(nuevo_autogenerado)
            impuc.autofac = autogenerado_factura
            impuc.cliente = fac.mcliente
            impuc.monto = fac.mtotal
            impuc.save()

            fac.msaldo = 0
            fac.save()

            # Guardar clones
            Movims.objects.bulk_create(nuevos_movims)
            Boleta.objects.bulk_create(nuevos_boleta)
            Asientos.objects.bulk_create(nuevos_asientos)

            nueva_nota = Movims.objects.filter(mautogen=nuevo_autogenerado).first()
            boleta_nc=Boleta.objects.filter(autogenerado=nuevo_autogenerado)
            monto_iva=0
            monto_exento=0

            for b in boleta_nc:
                if b.iva == 'Basico' or b.iva == 'Básico':
                    monto_iva += b.precio
                else:
                    monto_exento+=b.precio

            monto_iva=round(monto_iva,2)
            monto_exento=round(monto_exento,2)

            facturar_uruware_nc_directa(numero_nc,tipo_nota,nueva_nota.mserie,nueva_nota.mmoneda,nueva_nota.mcliente,nueva_nota.mtotal,nueva_nota.mmonto,
                                        nueva_nota.miva,nuevo_autogenerado,fac.mautogen,nueva_nota.mfechamov,nueva_nota.marbitraje,monto_iva,monto_exento)

        return JsonResponse({"mensaje": "Nota de crédito creada con éxito."})
    except Exception as e:
        return JsonResponse({"mensaje": f"Error al crear nota de crédito: {str(e)}"}, status=500)

def facturar_uruware_nc_directa(numero, tipo, serie, moneda, cliente_codigo, precio_total, neto, iva, nota_creada, factura_autogen,
                     fecha, arbitraje, mnto_neto, exento):
    numero = int(numero)

    try:
        tipo_cfe = None
        if int(tipo) == 23:
            # nc eticket
            tipo_cfe = 102
        elif int(tipo) == 24:
            # eticket
            tipo_cfe = 101
        elif int(tipo) == 21:
            # nc factura
            tipo_cfe = 112
        elif int(tipo) == 22:
            tipo_cfe = 112
        elif int(tipo) == 20:
            # efactura
            tipo_cfe = 111

        ui_valor = 0
        dolar_hoy = Dolar.objects.filter(ufecha__date=datetime.now()).first()
        if dolar_hoy:
            ui_valor = dolar_hoy.ui

        if arbitraje is None or arbitraje == 0:
            dolar_hoy = Dolar.objects.filter(ufecha__date=fecha).first()
            if dolar_hoy:
                arbitraje = dolar_hoy.uvalor

        moneda = int(moneda)
        cliente = Clientes.objects.filter(codigo=cliente_codigo).first()
        ciudad = None
        if cliente:
            ciudad = Ciudades.objects.filter(codigo=cliente.ciudad).first()
        #
        if not ciudad:
            return JsonResponse({"success": False, "mensaje": "El cliente no tiene una ciudad ingresada. Dirijase a mantenimientos y complete los datos para facturar."})

        items_nc = Boleta.objects.filter(autogenerado=nota_creada)

        data = {
            "tipo_cfe": tipo_cfe,
            "serie": serie,
            "numero": numero,
            "fecha_emision": fecha.strftime('%Y-%m-%d'),
            "forma_pago": "2",
            "ruc_emisor": "213971080016",
            "razon_social": "Oceanlink LTDA",
            "codigo_sucursal": "1",
            "domicilio": "Bolonia 2280 LATU, Edificio Los Álamos, Of.103",
            "ciudad": "Montevideo",
            "departamento": "Montevideo",
            "moneda": "UYU" if moneda and moneda == 1 else "USD" if moneda and moneda == 2 else "EUR" if moneda and moneda == 3 else "Error",
            "neto_tasa_basica": mnto_neto,
            "iva_tasa_basica": "22",
            "iva_monto_basica": iva,
            "total": precio_total,
            "cantidad_items": len(items_nc),
            "monto_pagar": precio_total,
            "monto_exento": Decimal(exento) if Decimal(exento) != 0 else '',
            "tipo_cambio": arbitraje,
            "hay_items_iva": False,
            "hay_items_exento": False,
            "tipo_doc_receptor": 2,
            "pais_codigo": "UY",
            "documento_receptor": cliente.ruc if cliente else '',
            "razon_social_receptor": cliente.razonsocial if cliente else '',
            "direccion_receptor": cliente.direccion if cliente else '',
            "ciudad_receptor": ciudad.nombre if ciudad else 'Montevideo',
            "pais_receptor": cliente.pais if cliente else '',
            "lleva_receptor": False,
            "es_extranjero": True if cliente.pais != 'Uruguay' else False,
        }
        data = {k: escape(str(v)) if isinstance(v, str) else v for k, v in data.items()}

        if tipo in (23, 24):
            # Calcular tope en pesos
            tope_ui = Decimal("5000") * Decimal(ui_valor or 0)

            supera_tope = False
            if moneda == 1:  # pesos
                supera_tope = Decimal(precio_total) > tope_ui
            elif moneda == 2:  # dólares
                supera_tope = Decimal(precio_total) * Decimal(arbitraje or 0) > tope_ui

            if supera_tope:
                # podés setear un flag en data
                data["lleva_receptor"] = True
            else:
                data["lleva_receptor"] = False

        items = []
        for i, item in enumerate(items_nc, start=1):

            if item.iva == 'Basico' or item.iva == 'Básico':
                data['hay_items_iva'] = True
            else:
                data['hay_items_exento'] = True

            items.append({
                "nro": i,
                "ind_fact": 3 if item.iva == 'Basico' or item.iva == 'Básico' else 1,
                "nombre": escape(item.concepto),
                "cantidad": 1,
                "unidad": "N/A",
                "precio_unitario": item.precio,
                "monto": item.precio,
            })

        referencias = []
        factura = Movims.objects.filter(mautogen=factura_autogen).first()
        tipo_fac = 101 if factura.mtipo == 24 else 111 if factura.mtipo == 20 else 'error'
        referencias.append({
            "nro_linea": 1,
            "tipo_doc": tipo_fac,
            "serie": factura.mserie if factura else '',
            "numero_cfe": factura.mboleta if factura else '',
            "fecha_cfe": factura.mfechamov.strftime('%Y-%m-%d') if factura else '',
        })
        # hacer el dict de las referencias cuando es nota d ecredito
        ucfe = UCFEClient(
            base_url="https://test.ucfe.com.uy/Inbox115/CfeService.svc",
            usuario="213971080016",
            rut="213971080016",
            clave="9rtcl5NzMXlRHKU2PGtPUw==",
            cod_comercio="OCEANL-394",
            cod_terminal="FC-394",
            wsdl_inbox="https://test.ucfe.com.uy/Inbox115/CfeService.svc?singleWsdl",
            wsdl_query="https://test.ucfe.com.uy/Query116/WebServicesFE.svc?singleWsdl"
        )
        if ucfe.is_folio_free(tipo_cfe, serie, numero, "213971080016"):
            xml = ucfe.render_xml(data, items, referencias)
            uuid_val = str(uuid.uuid4())

            resp_firma = ucfe.soap_solicitar_firma(
                xml,
                uuid_str=uuid_val,
                rut_emisor="213971080016",
                tipo_cfe=tipo_cfe,
                serie=serie,
                numero=numero
            )
            data_firma = serialize_object(resp_firma)
            cae_num = data_firma["Resp"].get("IdCae")

            for b in items_nc:
                b.cae=cae_num
                b.save()


            resp_post = ucfe.soap_obtener_cfe_emitido(
                rut="213971080016",
                tipo_cfe=tipo_cfe,
                serie=serie,
                numero=numero
            )
            data_post = serialize_object(resp_post)

            # ucfe.test_obtener_pdf("213971080016", tipo_cfe, serie, numero)

            if data_post:
                return {
                    "success": True,
                    "mensaje": f"CFE {tipo_cfe}-{serie}-{numero} registrado",
                    "xml": xml,
                    "ucfe_response": data_post,
                }
            else:
                logging.info(f"Error al firmar: {data_firma} {xml}")
                return {
                    "success": False,
                    "mensaje": f"Error al enviar a DGI {tipo_cfe}-{serie}-{numero}",
                    "xml": xml,
                }
        else:
            return {"success": False, "mensaje": "Número de folio no disponible"}

    except Exception as e:
        logging.info(f"Error: {e}")
        return {"success": False, "mensaje": str(e)}

def refacturar_uruware(request):
    autogenerado = request.POST.get("autogenerado")
    try:
        factura = Movims.objects.filter(mautogen=autogenerado).first()
        bol = Boleta.objects.filter(autogenerado=autogenerado).first()
        if not factura:
            return JsonResponse({"success": False, "mensaje": "Factura no encontrada"})

        tipo = factura.mtipo
        moneda = factura.mmoneda
        cliente_codigo=factura.mcliente
        serie = factura.mserie
        numero = int(bol.numero)
        fecha = factura.mfechamov
        arbitraje = factura.marbitraje
        iva = factura.miva
        precio_total = factura.mtotal

        ui_valor = 0
        dolar_hoy = Dolar.objects.filter(ufecha__date=datetime.now()).first()
        if dolar_hoy:
            ui_valor = dolar_hoy.ui

        if arbitraje is None or arbitraje == 0:
            dolar_hoy = Dolar.objects.filter(ufecha__date=fecha).first()
            if dolar_hoy:
                arbitraje = dolar_hoy.uvalor


        tipo_cfe = None
        if int(tipo) == 23:
            # nc eticket
            tipo_cfe = 102
        elif int(tipo) == 24:
            # eticket
            tipo_cfe = 101
        elif int(tipo) == 21:
            # nc factura
            tipo_cfe = 112
        elif int(tipo) == 22:
            tipo_cfe = 112
        elif int(tipo) == 20:
            # efactura
            tipo_cfe = 111

        asociadas = None
        if tipo == 21 or tipo == 23:
            #traer facturas asociadas
            asociadas=Impuvtas.objects.filter(autogen=autogenerado)

        moneda = int(moneda)
        cliente = Clientes.objects.filter(codigo=cliente_codigo).first()
        ciudad = None
        if cliente:
            ciudad = Ciudades.objects.filter(codigo=cliente.ciudad).first()

        if not ciudad:
            return JsonResponse({"success": False, "mensaje": "El cliente no tiene una ciudad ingresada. Dirijase a mantenimientos y complete los datos para facturar."})

        #
        items_factura = Boleta.objects.filter(autogenerado=autogenerado)

        monto_iva = 0
        monto_exento = 0

        for b in items_factura:
            if b.iva == 'Basico' or b.iva=='Básico':
                monto_iva += b.precio
            else:
                monto_exento += b.precio

        data = {
            "tipo_cfe": tipo_cfe,
            "serie": serie,
            "numero": numero,
            "fecha_emision": fecha.strftime('%Y-%m-%d'),
            "forma_pago": "2",
            "ruc_emisor": "213971080016",
            "razon_social": "Oceanlink LTDA",
            "codigo_sucursal": "1",
            "domicilio": "Bolonia 2280 LATU, Edificio Los Álamos, Of.103",
            "ciudad": "Montevideo",
            "departamento": "Montevideo",
            "moneda": "UYU" if moneda and moneda == 1 else "USD" if moneda and moneda == 2 else "EUR" if moneda and moneda == 3 else "Error",
            "neto_tasa_basica": round(monto_iva,2),
            "iva_tasa_basica": "22",
            "iva_monto_basica": round(iva,2),
            "total": precio_total,
            "cantidad_items": len(items_factura),
            "monto_pagar": precio_total,
            "monto_exento": round(Decimal(monto_exento),2) if Decimal(monto_exento) != 0 else '',
            "tipo_cambio": arbitraje,
            "hay_items_iva": False,
            "hay_items_exento": False,
            "tipo_doc_receptor": 2,
            "pais_codigo": "UY",
            "documento_receptor": cliente.ruc if cliente else '',
            "razon_social_receptor": cliente.razonsocial if cliente else '',
            "direccion_receptor": cliente.direccion if cliente else '',
            "ciudad_receptor": ciudad.nombre if ciudad else '',
            "pais_receptor": cliente.pais if cliente else '',
            "lleva_receptor": False,
            "es_extranjero": True if cliente.pais !='Uruguay' else False,
        }
        data = {k: escape(str(v)) if isinstance(v, str) else v for k, v in data.items()}
        if tipo in (23, 24):
            # Calcular tope en pesos
            tope_ui = Decimal("5000") * Decimal(ui_valor or 0)

            supera_tope = False
            if moneda == 1:  # pesos
                supera_tope = Decimal(precio_total) > tope_ui
            elif moneda == 2:  # dólares
                supera_tope = Decimal(precio_total) * Decimal(arbitraje or 0) > tope_ui

            if supera_tope:
                # podés setear un flag en data
                data["lleva_receptor"] = True
            else:
                data["lleva_receptor"] = False

        items = []
        for i, item in enumerate(items_factura, start=1):

            if item.iva == 'Basico' or item.iva == 'Básico':
                data['hay_items_iva'] = True
            else:
                data['hay_items_exento'] = True

            items.append({
                "nro": i,
                "ind_fact": 3 if item.iva == 'Basico' or item.iva == 'Básico' else 1,
                "nombre": escape(item.concepto),
                "cantidad": 1,
                "unidad": "N/A",
                "precio_unitario": item.precio,
                "monto": item.precio,
            })

        referencias = []
        if asociadas:
            for f in asociadas:
                factura = Movims.objects.filter(mautogen=f.autofac).first()
                tipo_fac = 101 if factura.mtipo == 24 else 111 if factura.mtipo == 20 else 'error'
                referencias.append({
                    "nro_linea": 1,
                    "tipo_doc": tipo_fac,
                    "serie": factura.mserie if factura else '',
                    "numero_cfe": factura.mboleta if factura else '',
                    "fecha_cfe": factura.mfechamov.strftime('%Y-%m-%d') if factura else '',
                })
        # hacer el dict de las referencias cuando es nota d ecredito
        ucfe = UCFEClient(
            base_url="https://test.ucfe.com.uy/Inbox115/CfeService.svc",
            usuario="213971080016",
            rut="213971080016",
            clave="9rtcl5NzMXlRHKU2PGtPUw==",
            cod_comercio="OCEANL-394",
            cod_terminal="FC-394",
            wsdl_inbox="https://test.ucfe.com.uy/Inbox115/CfeService.svc?singleWsdl",
            wsdl_query="https://test.ucfe.com.uy/Query116/WebServicesFE.svc?singleWsdl"
        )
        if ucfe.is_folio_free(tipo_cfe, serie, numero, "213971080016"):
            xml = ucfe.render_xml(data, items, referencias)
            uuid_val = str(uuid.uuid4())

            resp_firma = ucfe.soap_solicitar_firma(
                xml,
                uuid_str=uuid_val,
                rut_emisor="213971080016",
                tipo_cfe=tipo_cfe,
                serie=serie,
                numero=numero
            )
            data_firma = serialize_object(resp_firma)
            cae_num = data_firma["Resp"].get("IdCae")

            for b in items_factura:
                b.cae=cae_num
                b.save()


            resp_post = ucfe.soap_obtener_cfe_emitido(
                rut="213971080016",
                tipo_cfe=tipo_cfe,
                serie=serie,
                numero=numero
            )
            data_post = serialize_object(resp_post)

            if data_post:
                return JsonResponse({
                    "success": True,
                    "mensaje": f"CFE {serie}-{numero} registrado",
                    "xml": xml,
                    "ucfe_response": data_post,
                })
            else:
                logging.info(f"Error al firmar: {data_firma} {xml}")
                return JsonResponse({
                    "success": False,
                    "mensaje": f"Error al enviar a DGI {tipo_cfe}-{serie}-{numero}",
                    "xml": xml,
                })
        else:
            return JsonResponse({"success": False, "mensaje": "Número de folio no disponible"})

    except Exception as e:
        logging.info(f"Error al refacturar: {e}")
        return JsonResponse({"success": False, "mensaje": str(e)})

def descargar_pdf_uruware(request):
    autogenerado = request.POST.get("autogenerado")
    try:
        factura = Movims.objects.filter(mautogen=autogenerado).first()
        bol = Boleta.objects.filter(autogenerado=autogenerado).first()
        if not factura:
            return JsonResponse({"success": False, "mensaje": "Factura no encontrada"})

        tipo = factura.mtipo
        serie = factura.mserie
        numero = bol.numero

        tipo_cfe = None
        if int(tipo) == 23:
            tipo_cfe = 102
        elif int(tipo) == 24:
            tipo_cfe = 101
        elif int(tipo) == 21 or int(tipo) == 22:
            tipo_cfe = 112
        elif int(tipo) == 20:
            tipo_cfe = 111

        ucfe = UCFEClient(
            base_url="https://test.ucfe.com.uy/Inbox115/CfeService.svc",
            usuario="213971080016",
            rut="213971080016",
            clave="9rtcl5NzMXlRHKU2PGtPUw==",
            cod_comercio="OCEANL-394",
            cod_terminal="FC-394",
            wsdl_inbox="https://test.ucfe.com.uy/Inbox115/CfeService.svc?singleWsdl",
            wsdl_query="https://test.ucfe.com.uy/Query116/WebServicesFE.svc?singleWsdl"
        )

        resp = ucfe.soap_query.service.ObtenerPdf(
            rut="213971080016",
            tipoCfe=tipo_cfe,
            serieCfe=serie,
            numeroCfe=numero
        )

        if not resp:
            return JsonResponse({"success": False, "mensaje": "No se pudo obtener el PDF"})

        # Caso 1: binario
        if isinstance(resp, (bytes, bytearray)) and resp.startswith(b"%PDF"):
            pdf_bytes = resp
        else:
            pdf_bytes = base64.b64decode(resp)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response['Content-Disposition'] = f'attachment; filename="CFE_{tipo_cfe}_{serie}{numero}.pdf"'
        return response

    except Exception as e:
        logging.info(f"Error al obtener PDF: {e}")
        return JsonResponse({"success": False, "mensaje": str(e)})
