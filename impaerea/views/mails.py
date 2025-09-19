import locale
from datetime import datetime
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
import base64
from django.views.decorators.csrf import csrf_exempt
from reportlab.lib.validators import isNumber

from cargosystem import settings
from impaerea.models import VGastosHouse, ImportEmbarqueaereo, ImportReservas, ImportConexaerea
from impaerea.models import VEmbarqueaereo, ImportCargaaerea, ImportServiceaereo, ImportEmbarqueaereo as Embarqueaereo
from impomarit.views.mails import formatear_linea
from login.models import AccountEmail
from mantenimientos.views.bancos import is_ajax
from mantenimientos.models import Productos, Monedas, Clientes, Servicios, Ciudades
from seguimientos.models import VGrillaSeguimientos

DIAS_SEMANA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
         'octubre', 'noviembre', 'diciembre']
TIPOS_OPERATIVA = {
    'IMPORT MARITIMO': 'IMPORTACION MARITIMA',
    'EXPORT MARITIMO': 'EXPORTACION MARITIMA',
    'IMPORT AEREO': 'IMPORTACION AEREA',
    'EXPORT AEREO': 'EXPORTACION AEREA',
    'IMPORT TERRESTRE': 'IMPORTACION TERRESTRE',
    'EXPORT TERRESTRE': 'EXPORTACION TERRESTRE',
}


# Formateamos las fechas con strftime para mostrar en dd/mm/YY
def format_fecha(fecha):
    return fecha.strftime('%d/%m/%Y') if fecha is not None else "S/I"


@csrf_exempt
@login_required(login_url='/')
def get_data_email_op(request):
    resultado = {}
    if is_ajax(request):
        try:
            title = request.POST['title']
            row_number = request.POST['row_number']
            transportista = request.POST['transportista']
            master_boolean = request.POST['master']
            gastos_boolean = request.POST['gastos']
            directo_boolean = request.POST['directo']
            #armador = request.POST['armador']

            #9155
            embarque=ImportEmbarqueaereo.objects.get(numero=row_number)
            row = VEmbarqueaereo.objects.get(numero=row_number)
            row2 = ImportCargaaerea.objects.filter(numero=row_number)
            gastos = VGastosHouse.objects.filter(numero=row_number)
            #master=ImportReservas.objects.filter(awb=embarque.awb)
            email_cliente = Clientes.objects.get(codigo=embarque.consignatario).emailia if embarque.consignatario is not None else 'S/I'
            email_agente = Clientes.objects.get(codigo=embarque.agente).emailia if embarque.agente is not None else 'S/I'
            conex = ImportConexaerea.objects.filter(numero=embarque.numero)
            if conex:
                vapor = conex[0].vuelo if conex[0].vuelo else 'S/I'
            else:
                vapor = 'S/I'
            try:
                seg = VGrillaSeguimientos.objects.get(numero=row.seguimiento)
                seguimiento = VGrillaSeguimientos.objects.get(numero=row.seguimiento)

            except VGrillaSeguimientos.DoesNotExist:
                seguimiento = VGrillaSeguimientos(numero='', eta=None, etd=None, refcliente='', deposito='', pago='',vendedor='')
                seg = VGrillaSeguimientos(numero='', eta=None, etd=None, refcliente='', deposito='', pago='',vendedor='')

            texto = ''
            texto += f'<br>'
            texto, resultado = get_data_html(row_number, row, row2,seg, title, texto, resultado,seguimiento,gastos,embarque,conex,vapor,transportista,master_boolean,gastos_boolean,directo_boolean,request)
            estilo = "font-family: Courier New, Courier, monospace; font-size: 12px;"
            texto += f"<div style='{estilo}'>Agradeciendo vuestra preferencia, le saludamos muy atentamente.</div></br>"
            texto += f"<div style='{estilo}'>{request.user.first_name} {request.user.last_name}</div>"
            texto += f"<div style='{estilo}'>{request.user.email}</div>"
            texto += f"<div style='{estilo}; font-weight: bold;'>DEPARTAMENTO DE IMPORT AEREO</div>"
            texto += f"<div style='{estilo}'>{settings.EMPRESA_firma}</div>"
            texto += f"<div style='{estilo}'>PH: +598 26052332</div>"
            resultado['email_cliente'] = email_cliente
            resultado['email_agente'] = email_agente
            emails_disponibles = list(AccountEmail.objects.filter(user=request.user).values_list('email', flat=True))
            resultado['emails_disponibles'] = emails_disponibles
            resultado['resultado'] = 'exito'
            resultado['mensaje'] = texto
            resultado['asunto']=str(title.upper())+' - '+str(resultado['asunto'])

        except Exception as e:
            resultado['resultado'] = str(e)
    else:
        resultado['resultado'] = 'Ha ocurrido un error.'
    data_json = json.dumps(resultado)
    mimetype = "application/json"
    return HttpResponse(data_json, mimetype)


def get_data_html(row_number, row, row2,seg, title, texto, resultado,seguimiento,gastos,embarque,conex,vapor,transportista_boolean,master_boolean,gastos_boolean,directo_boolean,request):
    # merca = Productos.objects.get(codigo=row2.producto.codigo)
    try:
        if row2 is not None:
            merca = []
            for m in row2:
                merca.append(m.producto)
        fecha_actual = datetime.now()
        pago = 'COLLECT' if row.pago_flete == 'C' else 'PREPAID' if row.pago_flete == 'P' else 'S/I'

        if title == 'Notificación de transbordo de carga':
            fecha_actual = datetime.now()

            resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) + '- H B/L: ' + str(row.hawb) + '- Shipper: ' + str(
                row.embarcador) + '- Consignee: ' + str(row.consignatario)

            fecha_formateada = fecha_actual.strftime(
                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y'
            )

            texto += fecha_formateada.capitalize().upper() + '<br><br>'

            # Bultos y pesos
            cont = 1
            for b in row2:
                texto += formatear_linea(f"Bultos {cont}", b.bultos if b.bultos is not None else "S/I")
                texto += formatear_linea(f"Peso {cont}", b.bruto if b.bruto is not None else "S/I")
                cont += 1
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()
            # Datos generales
            texto += formatear_linea("Vuelo", str(vapor))
            texto += formatear_linea("Viaje", str(seg.viaje) if seg.viaje is not None else "S/I")
            texto += formatear_linea("Llegada estimada", format_fecha(row.fecha_retiro))
            texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")
            texto += formatear_linea("B/L", str(row.awb) if row.awb is not None else "S/I")
            texto += formatear_linea("H B/L", str(row.hawb) if row.hawb is not None else "S/I")
            texto += formatear_linea("Referencia", str(row_number) if row_number is not None else "S/I")
            texto += formatear_linea("Posición", str(row.posicion) if row.posicion is not None else "S/I")
            texto += formatear_linea("Seguimiento", str(row.seguimiento) if row.seguimiento is not None else "S/I")
            texto += formatear_linea("Consignatario", str(row.consignatario) if row.consignatario is not None else "S/I")
            texto += formatear_linea("Embarcador", str(row.embarcador) if row.embarcador is not None else "S/I")
            texto += formatear_linea("Orden cliente", str(row.orden_cliente) if row.orden_cliente is not None else "S/I")
            texto += formatear_linea("Ref. proveedor", str(row.ref_proveedor) if row.ref_proveedor is not None else "S/I")
            texto += formatear_linea("Mercadería", str(merca) if merca is not None else "S/I")

            texto += "<br>"

            # Mini tabla final como líneas formateadas
            texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")
            texto += formatear_linea("Destino", str(destino.nombre) if destino is not None else "S/I")
            texto += formatear_linea("Vuelo/Vuelo", str(vapor))
            texto += formatear_linea("Viaje", str(seg.viaje) if seg.viaje is not None else "S/I")
            texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))
            texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))

            texto += "<br>"

            return texto, resultado
        elif title == 'Novedades sobre la carga':

            fecha_actual = datetime.now()

            resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) + ' - Shipper: ' + str(row.embarcador) + \
         \
                                      '; Consignee: ' + str(row.consignatario)

            fecha_formateada = fecha_actual.strftime(

                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y'

            )

            texto += fecha_formateada.capitalize().upper() + '<br><br>'

            # Datos generales

            texto += formatear_linea("Embarque", str(row.seguimiento) if row.seguimiento is not None else "S/I")

            texto += formatear_linea("Posición", str(row.posicion) if row.posicion is not None else "S/I")

            texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))

            texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()

            texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")

            texto += formatear_linea("Destino", str(destino.nombre) if destino is not None else "S/I")

            texto += formatear_linea("Vuelo", str(vapor) if vapor is not None else "S/I")

            texto += formatear_linea("H B/L", str(row.hawb) if row.hawb is not None else "S/I")
            texto += formatear_linea("Embarcador", str(row.embarcador) if row.embarcador is not None else "S/I")

            texto += formatear_linea("Consignatario", str(row.consignatario) if row.consignatario is not None else "S/I")



            # Mercaderías
            if merca:
                nombres_merc = [m.nombre if m.nombre else "S/I" for m in merca]
                texto += formatear_linea("Mercadería", ", ".join(nombres_merc))

            # Bultos, peso y CBM
            if row2:
                bultos = [str(b.bultos) if b.bultos else "S/I" for b in row2]
                pesos = [str(b.bruto) if b.bruto else "S/I" for b in row2]
                cbms = []
                for b in row2:
                    if b.medidas:
                        medidas = b.medidas.strip().lower().replace('x', '×').replace('×', 'x').split('x')
                        if len(medidas) == 3 and all(m.replace('.', '', 1).isdigit() for m in medidas):
                            try:
                                largo, ancho, alto = map(float, medidas)
                                volumen = round(largo * ancho * alto * float(b.bultos or 1))
                                cbms.append(str(volumen))
                            except Exception:
                                cbms.append("S/I")
                        else:
                            cbms.append("S/I")
                    else:
                        cbms.append("S/I")

                texto += formatear_linea("Bultos", ", ".join(bultos))
                texto += formatear_linea("Peso", ", ".join(pesos))
                texto += formatear_linea("CBM", ", ".join(cbms))
            texto += ('Los buques y las llegadas al puerto de Montevideo son siempre a CONFIRMAR, ya </br>'
                      ' que puede haber trasbordos y/o alteraciones en las fechas estimadas de llegada </br>'
                      'sin previo aviso, por lo cual sugerimos consultarnos por la fecha de arribo que aparece en este aviso.')
            texto += "<br>"

            return texto, resultado
        elif title == 'Routing Order':

            hora_actual = datetime.now().strftime("%H:%M")

            fecha_actual = datetime.now()

            resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) +  ' - Shipper: ' + str(row.embarcador) + \
     \
                                  '; Consignee: ' + str(row.consignatario)

            texto += f'{hora_actual} <br><br>'

            texto += formatear_linea("Fecha", format_fecha(fecha_actual))

            texto += formatear_linea("A", str(row.agente) if row.agente else "S/I")

            texto += formatear_linea("Departamento", "MARITIMO")

            texto += "<br>"

            texto += "Estimados Sres.: <br>"

            texto += "Por favor, contactar la siguiente compañía para coordinar la operación referenciada: <br><br>"

            # Datos del proveedor

            texto += formatear_linea("Proveedor", str(row.embarcador) if row.embarcador else "S/I")

            texto += formatear_linea("Dirección", str(row.direccion_embarcador) if row.direccion_embarcador else "S/I")

            texto += formatear_linea("Ciudad", str(row.ciudad_embarcador) if row.ciudad_embarcador else "S/I")

            texto += formatear_linea("País", str(row.pais_embarcador) if row.pais_embarcador else "S/I")

            texto += "<br>"

            # Datos del consignatario

            texto += formatear_linea("Consignatario", str(row.consignatario) if row.consignatario else "S/I")

            texto += formatear_linea("Dirección", str(row.direccion_consignatario) if row.direccion_consignatario else "S/I")

            texto += formatear_linea("Ciudad", str(row.ciudad_consignatario) if row.ciudad_consignatario else "S/I")

            texto += formatear_linea("País", str(row.pais_consignatario) if row.pais_consignatario else "S/I")

            texto += "<br>"

            # Datos de la operación

            texto += formatear_linea("Referencia interna", str(row_number) if row_number else "S/I")

            texto += formatear_linea("Orden cliente", str(row.orden_cliente) if row.orden_cliente else "S/I")
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()

            texto += formatear_linea("Origen", str(origen.nombre) if origen else "S/I")

            texto += formatear_linea("Destino", str(destino.nombre) if destino else "S/I")

            texto += "<br>"

            # Mercadería y carga

            cont = 1

            for m in merca:
                texto += formatear_linea(f"Mercadería {cont}", str(m.nombre) if m.nombre else "S/I")

                cont += 1

            cont = 1

            for b in row2:
                texto += formatear_linea(f"Bultos {cont}", b.bultos if b.bultos is not None else "S/I")

                texto += formatear_linea(f"Peso {cont}", b.bruto if b.bruto is not None else "S/I")

                cont += 1

            texto += formatear_linea("Condiciones de pago", str(row.pago_flete) if row.pago_flete else "S/I")

            texto += formatear_linea("Términos de compra", str(row.terminos) if row.terminos else "S/I")

            texto += formatear_linea("Modo de embarque", "MARITIMO")

            texto += "<br>"

            return texto, resultado
        elif title == 'Notificación de llegada de carga':
            refcliente = seguimiento.refcliente if seguimiento.refcliente else "S/I"

            resultado['asunto'] = (

                f' Ref.: {row.seguimiento} -'
    
                f'HB/l: {row.hawb} - Ship: {row.embarcador} - Consig: {row.consignatario}; Vuelo: {vapor}; Ord. Cliente: {refcliente}'

            )

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

            consigna = Clientes.objects.get(codigo=embarque.consignatario)

            carga = ImportCargaaerea.objects.filter(numero=embarque.numero)

            gastos = ImportServiceaereo.objects.filter(numero=embarque.numero)

            texto = formatear_linea("Fecha", fecha_formateada)

            texto += "<br>"

            texto += formatear_linea("Att.", "")

            texto += formatear_linea("Notificar a", row.consignatario)

            texto += formatear_linea("Dirección", consigna.direccion if consigna else "")

            texto += formatear_linea("Teléfono", consigna.telefono if consigna else "")

            texto += "<br>"
            salida = seg.etd.strftime("%d/%m/%Y") if isinstance(seg.etd, datetime) else ''

            llegada = seg.eta.strftime("%d/%m/%Y") if isinstance(seg.eta, datetime) else ''

            texto += formatear_linea("Salida", salida )

            texto += formatear_linea("Llegada", llegada )
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()
            texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')
            texto += formatear_linea("Destino", destino.nombre if destino else 'S/I' )

            texto += formatear_linea("HAWB", embarque.hawb)

            if master_boolean == 'true':
                texto += formatear_linea("AWB", embarque.awb)

            texto += formatear_linea("Referencia", row.seguimiento)

            texto += formatear_linea("Posición", embarque.posicion)

            texto += formatear_linea("Seguimiento", row.seguimiento)

            if conex:
                for i, ruta in enumerate(conex):
                    if ruta.salida:
                        fecha = ruta.salida.strftime("%d-%m")
                    else:
                        fecha = '??/??'
                    tramo = f"({ruta.origen}/{ruta.destino})   {ruta.ciavuelo}{ruta.viaje}/{fecha}"
                    texto += formatear_linea("Vuelo", tramo)

            texto += formatear_linea("Embarcador", row.embarcador)

            texto += formatear_linea("Ref. Proveedor", row.embarcador)

            volumen=0
            if carga:

                for c in carga:

                    if c.medidas is not None:

                        medidas = c.medidas.split('*')

                    else:

                        medidas = None

                    if medidas and len(medidas) == 3 and all(m.isdigit() for m in medidas):

                        volumen = float(medidas[0]) * float(medidas[1]) * float(medidas[2])

                        ap1 = volumen * 166.67

                    else:

                        ap1 = 0
                    bruto = float(c.bruto) if c.bruto else 0
                    aplicable = round(ap1, 2) if ap1 > bruto else bruto

                    texto += formatear_linea("Mercadería", c.producto.nombre)

                    texto += formatear_linea("Bultos", str(c.bultos))

                    texto += formatear_linea("Peso", bruto)

                    texto += formatear_linea("Aplicable", str(aplicable))
                    texto += formatear_linea("CBM", str(volumen or 'S/I')+' M³')


                texto += "<br>"

            if gastos_boolean == 'true' and gastos:

                texto += '<p style="font-family: Courier New, monospace; font-size: 12px; line-height: 1;"> Detalle de gastos en Dólares U.S.A </p>'

                total_gastos = 0

                total_iva = 0

                for g in gastos:

                    servicio = Servicios.objects.get(codigo=g.servicio)

                    total_gastos += float(g.precio)

                    if servicio.tasa == 'B':
                        total_iva += float(g.precio) * 0.22

                    if g.precio != 0:
                        texto += formatear_linea(servicio.nombre, f"{g.precio:.2f}",1)

                texto += "<br>"

                texto += formatear_linea("TOTAL DE GASTOS", f"{total_gastos:.2f}",1)

                texto += formatear_linea("I.V.A", f"{total_iva:.2f}",1)

                texto += formatear_linea("TOTAL A PAGAR", f"{total_gastos + total_iva:.2f}",1)

                texto += "<br>"

            texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

            texto += "Les informamos que por razones de seguridad los pagos solo pueden hacerse por transferencia bancaria a la siguiente cuenta:\n\n"

            texto += "BBVA URUGUAY S.A.\n"

            texto += "25 de Mayo 401\n"

            texto += "Cuenta Número: 5207347\n"

            texto += "OCEANLINK Ltda.\n\n"

            texto += "Los buques, vuelos y las fechas pueden variar sin previo aviso y son siempre a CONFIRMAR.\n"

            texto += "</pre>"

            return texto, resultado
        elif title == 'Liberacion':

            resultado['asunto'] = f'{row.awb} - seguimiento: {row.seguimiento}'

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

            texto = ""

            texto += formatear_linea("Fecha", fecha_formateada)

            texto += "<br>"

            texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

            texto += f"ESTIMADOS,\n\n"

            texto += f"SOLICITAMOS LA LIBERACIÓN DEL SIGUIENTE BL: {row.awb}\n\n"

            texto += "ADJUNTAMOS:\n"

            texto += f" * BL {row.awb} ENDOSADO\n"

            texto += " * ARRIVAL NOTICE ENDOSADO\n"

            texto += " * CONTRATO DE RESPONSABILIDAD\n"

            texto += " * COMPROBANTE DE PAGO\n\n"

            texto += "SALUDOS,\n\n"

            texto += "OCEANLINK\n"

            texto += "</pre>"
        elif title == 'Aviso de embarque':
            refcliente = seguimiento.refcliente if seguimiento.refcliente else "S/I"

            resultado[
                'asunto'] = f'Ref: {row.seguimiento} - HB/l: {row.hawb} - Shipper: {row.embarcador} - Consig: {row.consignatario}; Ord. Cliente: {refcliente}'

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime(
                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')

            texto = formatear_linea("Fecha", fecha_formateada.capitalize())

            texto += "<br>"

            texto += formatear_linea("Sres.", str(row.consignatario))

            texto += formatear_linea("Depto.", "COMERCIO EXTERIOR")

            texto += "<br>"

            salida = seguimiento.etd.strftime("%d/%m/%Y") if isinstance(seguimiento.etd, datetime) else ""

            llegada = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ""

            ref = f"{row.seguimiento}"

            texto += formatear_linea("Referencia", ref)

            texto += formatear_linea("Posición", row.posicion or "")

            texto += formatear_linea("Consignatario", row.consignatario or "")

            texto += formatear_linea("Orden Cliente", embarque.ordencliente or "")

            texto += formatear_linea("Ref. Proveedor", embarque.refproveedor or "")

            texto += formatear_linea("Términos de Compra", row.terminos or "")
            texto += formatear_linea("HAWB", row.hawb or "")

            if master_boolean == 'true':
                texto += formatear_linea("AWB", row.awb or "")

            if transportista_boolean == 'true':
                texto += formatear_linea("Transportista", row.transportista or "")

            if conex:
                for i, ruta in enumerate(conex):
                    if ruta.salida:
                        fecha = ruta.salida.strftime("%d-%m")
                    else:
                        fecha = '??/??'
                    tramo = f"({ruta.origen}/{ruta.destino})   {ruta.ciavuelo}{ruta.viaje}/{fecha}"
                    texto += formatear_linea("Vuelo", tramo)

            #origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()

            texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')

            texto += formatear_linea("Destino", destino.nombre if destino else 'S/I')

            texto += formatear_linea("Salida", salida)

            texto += formatear_linea("Llegada", llegada)

            texto += "<br>"

            texto += formatear_linea("Agente", row.agente or "")

            # Datos de contenedores

            mercaderias = ""

            bultos = 0

            peso = 0

            volumen = 0

            cant_cntr = ImportCargaaerea.objects.filter(numero=row.numero).values(

                'medidas', 'bruto', 'bultos', 'producto'

            ).annotate(total=Count('id'))

            if cant_cntr.exists():

                for cn in cant_cntr:

                    if cn['medidas']:

                        medidas = cn['medidas'].split('*')

                        if len(medidas) == 3 and all(m.isdigit() for m in medidas):
                            volumen = float(medidas[0]) * float(medidas[1]) * float(medidas[2])

                    bultos += cn['bultos'] if cn['bultos'] else 0

                    peso += cn['bruto'] if cn['bruto'] else 0

                    producto = Productos.objects.get(codigo=int(cn['producto'])).nombre

                    mercaderias += producto + ' - '

            texto += formatear_linea("House", row.hawb or "")

            texto += formatear_linea("Peso", f"{peso} KGS",)

            texto += formatear_linea("Bultos", str(bultos),)

            texto += formatear_linea("CBM", f"{volumen:.3f} M³",)
            texto += formatear_linea("Aplicable", str(row.aplicable))
            texto += "<br>"

            texto += formatear_linea("Mercadería", mercaderias.rstrip(' -'))

            texto += formatear_linea("Depósito", seguimiento.deposito or "")



            if gastos_boolean == 'true':

                if gastos:

                    texto += '<p style="font-family: Courier New, monospace; font-size: 12px; line-height: 1;"> Detalle de gastos en Dólares U.S.A </p>'

                    total_gastos = 0

                    total_iva = 0

                    for g in gastos:

                        codigo = g.servicio.split(" - ")[0]
                        codigo = int(codigo) if isNumber(codigo) else None
                        if codigo is None:
                            raise TypeError('No se encontró el código del servicio')
                        servicio = Servicios.objects.get(codigo=codigo)

                        if servicio is not None:

                            if g.precio !=0 and g.precio is not None:
                                total_gastos += float(g.precio)
                            elif g.costo is not None and g.costo!=0:
                                total_gastos += float(g.costo)
                            else:
                                total_gastos+=0

                            iva = True if servicio.tasa == 'B' else False

                            if iva:
                                if g.precio is not None and g.precio !=0:
                                    total_iva += float(g.precio) * 0.22
                                elif g.costo is not None and g.costo !=0:
                                    total_iva +=float(g.costo) * 0.22
                                else:
                                    total_iva+=0

                            if g.precio is not None and g.precio !=0:
                                texto += formatear_linea(servicio.nombre, f"{g.precio:.2f}", 1)
                            elif g.costo is not None and g.costo !=0:
                                texto += formatear_linea(servicio.nombre, f"{g.costo:.2f}", 1)
                            else:
                                texto += formatear_linea("Problema con los gastos cargados", 0)

                    texto += "<br>"

                    texto += formatear_linea("TOTAL DE GASTOS", f"{total_gastos:.2f}", 1)

                    texto += formatear_linea("I.V.A", f"{total_iva:.2f}", 1)

                    texto += formatear_linea("TOTAL A PAGAR", f"{total_gastos + total_iva:.2f}", 1)

                    texto += "<br>"

            texto += "<br>"
            if conex:
                texto += "<table style='border: none; font-family: Courier New, monospace; font-size: 12px; border-collapse: collapse; width: 100%;'>"

                # Fila de títulos (encabezados)
                texto += "<tr>"
                texto += "<th style='padding: 2px 10px; text-align: left;'>Origen</th>"
                texto += "<th style='padding: 2px 10px; text-align: left;'>Destino</th>"
                texto += "<th style='padding: 2px 10px; text-align: left;'>Vapor/Vuelo</th>"
                texto += "<th style='padding: 2px 10px; text-align: left;'>Viaje</th>"
                texto += "<th style='padding: 2px 10px; text-align: left;'>Salida</th>"
                texto += "<th style='padding: 2px 10px; text-align: left;'>Llegada</th>"
                texto += "</tr>"

                # Fila de valores
                for c in conex:
                    salida = c.salida.strftime('%d/%m/%Y') if c.salida else 'S/i'
                    llegada = c.llegada.strftime('%d/%m/%Y') if c.llegada else 'S/i'
                    texto += "<tr>"
                    texto += f"<td style='padding: 2px 10px;'>{c.origen or ''}</td>"
                    texto += f"<td style='padding: 2px 10px;'>{c.destino or ''}</td>"
                    texto += f"<td style='padding: 2px 10px;'>{c.ciavuelo or ''}</td>"
                    texto += f"<td style='padding: 2px 10px;'>{c.viaje or ''}</td>"
                    texto += f"<td style='padding: 2px 10px;'>{salida}</td>"
                    texto += f"<td style='padding: 2px 10px;'>{llegada}</td>"
                    texto += "</tr>"

                texto += "</table><br>"

            texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

            texto += "Los vuelos y las llegadas al aeropuerto de Montevideo son siempre a CONFIRMAR, ya que puede haber trasbordos y/o alteraciones en las fechas estimadas de llegada\n"
            texto += "sin previo aviso, por lo cual le sugerimos consultarnos por la fecha de arribo que aparece en este aviso.\n"
            texto += "</pre>"
            return texto, resultado
        elif title == 'Aviso de desconsolidacion':

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime(
                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')

            resultado['asunto'] = (

                f'Ref.: {row.seguimiento} - HB/l: {row.hawb} - Ship: {row.embarcador}'


            )
            try:
                consigna=Clientes.objects.get(codigo=row.consignatario_id)
                telefono=consigna.telefono
            except Clientes.DoesNotExist:
                direccion=telefono='S/I'


            texto += formatear_linea("Fecha", fecha_formateada.upper())

            texto += "<br>"

            texto += formatear_linea("Att.", "DEPARTAMENTO DE OPERACIONES")

            texto += formatear_linea("Consignatario", str(row.consignatario))

            texto += formatear_linea("Dirección", row.direccion_consignatario or "")

            texto += formatear_linea("Teléfono", telefono or "")


           # texto += formatear_linea("Vapor", row.vapor or "")  # cambiar esto
            salida = seguimiento.etd.strftime("%d/%m/%Y") if isinstance(seguimiento.etd, datetime) else ""

            llegada = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ""

            texto += formatear_linea("Viaje", conex[0].viaje or "")

            texto += formatear_linea("Llegada", llegada)

            texto += formatear_linea("Posición", row.posicion or "")

            texto += formatear_linea("Seguimiento", row.seguimiento)

            texto += formatear_linea("Embarcador", row.embarcador)

            #texto += formatear_linea("Consignatario", row.consignatario)

            texto += formatear_linea("Orden cliente", seguimiento.refcliente)

            texto += formatear_linea("Referencia proveedor", seguimiento.refproveedor)
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()
            texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')

            texto += formatear_linea("Destino", destino.nombre if destino else 'S/I')

            # Datos de contenedores

            cantidad_cntr = ""

            contenedores = ""

            precintos = ""

            movimiento = ""

            mercaderias = ""

            bultos = 0

            peso = 0

            volumen = 0

            cant_cntr = ImportCargaaerea.objects.filter(numero=row.numero).values(

                'bruto', 'medidas', 'bultos','producto__nombre').annotate(total=Count('id'))

            if cant_cntr.count() > 0:

                for cn in cant_cntr:
                    bultos += cn['bultos'] if cn['bultos'] else 0
                    if cn['bruto']:
                        peso += cn['bruto']

                    if cn['medidas'] is not None:

                        medidas = cn['medidas'].split('*')

                    else:

                        medidas = None

                    if medidas and len(medidas) == 3 and all(m.isdigit() for m in medidas):

                        volumen += float(medidas[0]) * float(medidas[1]) * float(medidas[2])

                    else:
                        volumen+=0

                    mercaderias += f'{cn["producto__nombre"]} - '


            texto += formatear_linea("Bultos", str(bultos))

            texto += formatear_linea("Peso", f"{peso:.2f} KGS")

            texto += formatear_linea("CBM", f"{volumen:.2f} M³")

            texto += formatear_linea("Mercadería", mercaderias.strip(' -'))

            texto += formatear_linea("Depósito", str(seguimiento.deposito))
            texto += formatear_linea("WR", str(embarque.wreceipt))

            texto += "<br>"

            texto += "<b>ATENCION!</b><br><br>"

            texto += "DETALLE DE DESCONSOLIDACION<br><br>"
            return texto,resultado
        elif title == 'Orden de facturacion':

            resultado['asunto'] = 'seguimiento: ' + str(
                row.seguimiento)

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
            fecha_actual = datetime.now()
            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()
            if isinstance(seguimiento.eta, datetime):
                llegada = str(seguimiento.eta.strftime("%d/%m/%Y"))
            else:
                llegada = ''
            tabla_html = fecha_formateada+"<br><br>"
            tabla_html += f"<p>ORDEN DE FACTURACIÓN SEGUIMIENTO: {row.seguimiento}</p><br>"
            tabla_html += f"<p>POSICIÓN: {row.posicion}</p><br>"
            tabla_html += f"<p>MASTER: {row.awb}</p><br>"
            tabla_html += f"<p>ETA {llegada} </p><br>"
            tabla_html += f"<p>CLIENTE: {seguimiento.cliente}</p><br>"

            return tabla_html, resultado
        elif title == 'Notificacion cambio de linea':

            resultado['asunto'] = '/ NVOCC / CÍA AEREA'

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

            texto = ""

            texto += formatear_linea("Fecha", fecha_formateada)

            texto += "<br>"

            texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

            texto += f"SEG: {row.seguimiento}\n\n"

            texto += "CONFIRMO CAMBIO DE LÍNEA / NVOCC / CÍA AÉREA DE ESTE SEGUIMIENTO\n\n"

            texto += "ANTERIOR:\n"

            texto += f"ACTUAL: {row.transportista}\n\n"

            texto += "OCEANLINK\n"

            texto += "</pre>"

            return texto, resultado
        elif title == 'Traspaso a operaciones':

            texto += formatear_linea("SEGUIMIENTO", row.seguimiento)

            texto += formatear_linea("CLIENTE", row.consignatario)

            texto += formatear_linea("BL", row.awb)

            texto += formatear_linea("HBL", row.hawb)

            texto += "<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>EMBARQUE TRASPASADO A DEPARTAMENTO DE OPERACIONES</p>"

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime(

                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')

            texto += formatear_linea("FECHA", fecha_formateada.capitalize())

            texto += formatear_linea("CONDICION MBL", "")

            texto += formatear_linea("CONDICION HBL", "")

            texto += formatear_linea("COURIER CON DOCS", "")

            texto += formatear_linea("COURIER/GUIA", "")

            resultado['asunto'] = f'SEGUIMIENTO {seguimiento.numero} // TRASPASO A OPERACIONES'

            return texto, resultado

        elif title == 'Shipping instruction':
            #embarcador = Clientes.objects.get(codigo=embarque.embarcador)
            consignatario = Clientes.objects.get(codigo=embarque.consignatario)
            cliente = Clientes.objects.get(codigo=embarque.cliente)
            agente = Clientes.objects.get(codigo=embarque.agente)
            mercaderia = ImportCargaaerea.objects.filter(numero=row.numero)
            moneda = Monedas.objects.get(codigo=embarque.moneda)
            ocean = Clientes.objects.get(codigo=835)

            try:
                if embarque.embarcador:
                    proveedor = Clientes.objects.get(codigo=embarque.embarcador)
                    direccion = proveedor.direccion
                    empresa = proveedor.empresa
                    ciudad = proveedor.ciudad
                    pais = proveedor.pais
                    email = proveedor.emailim
                    contactos = proveedor.contactos
                else:
                    direccion = empresa = ciudad = pais = email = contactos = ''
            except Clientes.DoesNotExist:
                direccion = empresa = ciudad = pais = email = contactos = ''

            resultado['asunto'] = f'Ref.: {seguimiento.numero} - Shipper: {empresa} - Consignee: {consignatario.empresa}'

            locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
            fecha_actual = datetime.now()
            fecha_formateada = fecha_actual.strftime('%A, %B %d, %Y').upper()
            llegada = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ''
            nombre = f"{request.user.first_name} {request.user.last_name}"

            texto = ''
            texto += formatear_linea("Date", fecha_formateada)
            texto += formatear_linea("To", agente.empresa)
            texto += formatear_linea("Department", "AIRFREIGHT")
            texto += formatear_linea("Sent by", nombre)

            texto += "<br><p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Dear colleagues:</p>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Please contact the following company to coordinate the following shipment as per our instructions below:</p>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Please ack this message and let us know status of cargo asap.</p><br>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Please add HS code on AWB an HAWB</p><br>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>AWB -</p>"
                texto_ocean = str(ocean.empresa) + ' ' + str(ocean.direccion) + ' ' + 'CP 11000 ' + str(
                    ocean.ruc) + ' ' + str(ocean.telefono)
                texto += formatear_linea("Shipper", agente.empresa)
                texto += formatear_linea("Consignee", texto_ocean)
            texto+='</br>'
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>{'HAWB' if directo_boolean == 'true' else 'AWB'}</p>"

            texto += formatear_linea("Shipper name", empresa)
            texto += formatear_linea("Address", direccion)
            texto += formatear_linea("City", ciudad)
            texto += formatear_linea("Country", pais)
            texto += formatear_linea("E-mail", email)
            texto += formatear_linea("Contacts", contactos)

            texto += "<br>"
            texto += formatear_linea("Consignee name", consignatario.empresa)
            texto += formatear_linea("Address", consignatario.direccion)
            texto += formatear_linea("Country", consignatario.pais)
            texto += formatear_linea("Tax ID", consignatario.ruc)
            texto += formatear_linea("Phone", consignatario.telefono)

            texto += "<br>"
            texto += formatear_linea("Internal Reference", f"{seguimiento.numero}/{row.numero}")
            texto += formatear_linea("Position", row.posicion)
            texto += formatear_linea("Estimated delivery date", llegada)

            origen_txt = 'S/I'
            destino_txt = 'S/I'

            if embarque.origen is not None:
                ciudad_l = Ciudades.objects.filter(codigo=embarque.origen).first()
                origen_txt = ciudad_l.nombre
            if embarque.destino is not None:
                ciudad_d = Ciudades.objects.filter(codigo=embarque.discharge).first()
                destino_txt = ciudad_d.nombre

            texto += formatear_linea("Airport of origin", origen_txt)
            texto += formatear_linea("Airport of destination", destino_txt)

            texto += "<br>"
            for m in mercaderia:
                peso = m.bruto if m.bruto else 0
                if m.medidas is not None:
                    medidas = m.medidas.split('*')
                else:
                    medidas = None

                if medidas and len(medidas) == 3 and all(m.isdigit() for m in medidas):
                    volumen = float(medidas[0]) * float(medidas[1]) * float(medidas[2])
                else:
                    volumen = 0
                calculado = volumen * 166.67
                aplicable = peso if peso > calculado else f"{calculado:.2f} AS VOL"

                texto += formatear_linea("Commodity", m.producto)
                texto += formatear_linea("Packages", m.bultos)
                texto += formatear_linea("Weight", f"{peso:.2f} KGS")
                texto += formatear_linea("Volume", f"{volumen:.2f} CBM")
                #texto += formatear_linea("Chargeable weight", aplicable)

            condicion_pago = "Collect" if row.pago_flete == "C" else "Prepaid" if row.pago_flete == "P" else "N/A"
            texto += formatear_linea("Payment terms", condicion_pago)
            texto += formatear_linea("Terms of purchase", row.terminos)
            if transportista_boolean == 'true':
                texto += formatear_linea("Carrier", row.transportista)

            texto += formatear_linea("Transport contract", seguimiento.contratotra)
            texto += formatear_linea("Mode of shipment", "AEREO")
            texto += formatear_linea("Currency", moneda.nombre if moneda is not None else 'S/I')
            texto += "<br>"
            return texto,resultado
        elif title == 'Instruccion de embarque':
            #embarcador = Clientes.objects.get(codigo=embarque.embarcador)
            consignatario = Clientes.objects.get(codigo=embarque.consignatario)
            cliente = Clientes.objects.get(codigo=embarque.cliente)
            agente = Clientes.objects.get(codigo=embarque.agente)
            mercaderia = ImportCargaaerea.objects.filter(numero=row.numero)
            moneda = Monedas.objects.get(codigo=embarque.moneda)
            ocean = Clientes.objects.get(codigo=835)

            try:
                if embarque.embarcador:
                    proveedor = Clientes.objects.get(codigo=embarque.embarcador)
                    direccion = proveedor.direccion
                    empresa = proveedor.empresa
                    ciudad = proveedor.ciudad
                    pais = proveedor.pais
                    email = proveedor.emailim
                    contactos = proveedor.contactos
                else:
                    direccion = empresa = ciudad = pais = email = contactos = ''
            except Clientes.DoesNotExist:
                direccion = empresa = ciudad = pais = email = contactos = ''

            resultado[
                'asunto'] = f"INSTRUCCIÓN DE EMBARQUE - Ref.: {seguimiento.numero} - Shipper: {empresa} - Consignee: {consignatario.empresa}"

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
            fecha_actual = datetime.now()
            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()
            llegada = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ''
            nombre = f"{request.user.first_name} {request.user.last_name}"

            texto = ''
            texto += formatear_linea("Fecha", fecha_formateada)
            texto += formatear_linea("A", agente.empresa)
            texto += formatear_linea("Departamento", "AEREO")
            texto += formatear_linea("Envíado", nombre)

            texto += "<br><p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Estimados Sres.:</p><br>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Por favor, contactar a la siguiente compañía para coordinar el siguiente embarque según nuestras instrucciones a continuación:</p>"
            texto += "<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Por favor confirmar este mensaje e informarnos el estado de la carga a la brevedad.</p><br>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Favor incluir el código HS en AWB y HAWB</p>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>AWB -</p>"
                ocean = Clientes.objects.get(codigo=835)
                texto_ocean = str(ocean.empresa) + ' ' + str(ocean.direccion) + ' CP 11000 ' + str(
                    ocean.ruc) + ' ' + str(ocean.telefono)
                texto += formatear_linea("Shipper", agente.empresa)
                texto += formatear_linea("Consignatario", texto_ocean)
            texto += "<br>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>{'HAWB' if directo_boolean == 'true' else 'AWB'}</p>"

            texto += formatear_linea("Proveedor", empresa)
            texto += formatear_linea("Dirección", direccion)
            texto += formatear_linea("Ciudad", ciudad)
            texto += formatear_linea("País", pais)
            texto += formatear_linea("E-mail", email)
            texto += formatear_linea("Contactos", contactos)

            texto += "<br>"
            texto += formatear_linea("Consignatario", consignatario.empresa)
            texto += formatear_linea("Dirección", consignatario.direccion)
            texto += formatear_linea("País", consignatario.pais)
            texto += formatear_linea("RUC", consignatario.ruc)
            texto += formatear_linea("Teléfono", consignatario.telefono)

            texto += "<br>"
            texto += formatear_linea("Referencia interna", f"{seguimiento.numero}")
            texto += formatear_linea("Posición", row.posicion)
            texto += formatear_linea("Recepción estimada de mercadería", llegada)
            origen_txt = 'S/I'
            destino_txt = 'S/I'

            if embarque.origen is not None:
                ciudad_l = Ciudades.objects.filter(codigo=embarque.origen).first()
                origen_txt = ciudad_l.nombre
            if embarque.destino is not None:
                ciudad_d = Ciudades.objects.filter(codigo=embarque.destino).first()
                destino_txt = ciudad_d.nombre

            texto += formatear_linea("Aeropuerto de origen", origen_txt)
            texto += formatear_linea("Aeropuerto de destino", destino_txt)

            texto += "<br>"
            for m in mercaderia:
                peso = m.bruto if m.bruto else 0
                if m.medidas is not None:
                    medidas = m.medidas.split('*')
                else:
                    medidas = None

                if medidas and len(medidas) == 3 and all(m.isdigit() for m in medidas):
                    volumen = float(medidas[0]) * float(medidas[1]) * float(medidas[2])
                else:
                    volumen =0
                calculado = volumen * 166.67
                aplicable = peso if peso > calculado else f"{calculado:.2f} AS VOL"

                texto += formatear_linea("Mercadería", m.producto)
                texto += formatear_linea("Bultos", m.bultos)
                texto += formatear_linea("Peso", f"{peso:.2f} KGS")
                texto += formatear_linea("Volumen", f"{volumen:.2f} CBM")
                #texto += formatear_linea("Aplicable", aplicable)

            texto += formatear_linea("Condiciones de pago",
                                     "Collect" if row.pago_flete == "C" else "Prepaid" if row.pago_flete == "P" else "S/I")
            texto += formatear_linea("Términos de compra", row.terminos)
            if transportista_boolean == 'true':
                texto += formatear_linea("Transportista", row.transportista)
            texto += formatear_linea("Contrato transport.", seguimiento.contratotra)
            texto += formatear_linea("Modo de embarque", "AÉREO")
            texto += formatear_linea("Moneda", moneda.nombre if moneda is not None else 'S/I')
            texto += "<br>"
            return texto,resultado

        return texto,resultado
    except Exception as e:
        raise TypeError(e)


def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
        return base64_data
