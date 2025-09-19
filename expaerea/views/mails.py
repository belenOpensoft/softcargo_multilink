import locale
from datetime import datetime
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
import base64
from django.views.decorators.csrf import csrf_exempt

from cargosystem import settings
from expaerea.models import VEmbarqueaereo, ExportCargaaerea, ExportServiceaereo, VGastosHouse, \
    ExportEmbarqueaereo as Embarqueaereo, ExportConexaerea
from login.models import AccountEmail
from mantenimientos.views.bancos import is_ajax
from mantenimientos.models import Productos, Clientes, Monedas, Servicios, Ciudades
from seguimientos.models import VGrillaSeguimientos
from impomarit.views.mails import formatear_linea

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
            master = request.POST['master']
            gastos_boolean = request.POST['gastos']
            #9155
            embarque=Embarqueaereo.objects.get(numero=row_number)
            row = VEmbarqueaereo.objects.get(numero=row_number)
            row2 = ExportCargaaerea.objects.filter(numero=row_number)
            gastos = VGastosHouse.objects.filter(numero=row_number)
            email_cliente = Clientes.objects.get(codigo=embarque.consignatario).emailea if embarque.consignatario is not None else 'S/I'
            email_agente = Clientes.objects.get(codigo=embarque.agente).emailea if embarque.agente is not None else 'S/I'
            conex = ExportConexaerea.objects.filter(numero=embarque.numero).order_by('-id').last()
            if conex:
                vapor = conex.vuelo if conex.vuelo else 'S/I'
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
            texto, resultado = get_data_html(row_number, row, row2,seg, title, texto, resultado,seguimiento,gastos,embarque,master,gastos_boolean,conex,vapor,request)
            estilo = "font-family: Courier New, Courier, monospace; font-size: 12px;"
            texto += f"<div style='{estilo}'>Agradeciendo vuestra preferencia, le saludamos muy atentamente.</div></br>"
            texto += f"<div style='{estilo}'>{request.user.first_name} {request.user.last_name}</div>"
            texto += f"<div style='{estilo}'>{request.user.email}</div>"
            texto += f"<div style='{estilo}; font-weight: bold;'>DEPARTAMENTO DE EXPORT AEREO</div>"
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


def get_data_html(row_number, row, row2,seg, title, texto, resultado,seguimiento,gastos,embarque,master,gastos_boolean,conex,vapor,request):
    """
    return: texto del mail y el asunto
    """
    if row2 is not None:
        merca = []
        for m in row2:
            merca.append(m.producto)

    fecha_actual = datetime.now()
    if title == 'Notificación de transbordo de carga':
        fecha_actual = datetime.now()
        resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) + '- H B/L: ' + str(row.hawb) + '- Shipper: ' + str(
            row.embarcador) + '- Consignee: ' + str(row.consignatario)

        fecha_formateada = fecha_actual.strftime(
            f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')
        texto += fecha_formateada.capitalize().upper() + '<br><br>'

        cont = 1
        for b in row2:
            texto += formatear_linea(f"Bultos {cont}", b.bultos if b.bultos is not None else "S/I")
            texto += formatear_linea(f"Peso {cont}", b.bruto if b.bruto is not None else "S/I")
            cont += 1
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

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

        # Mini tabla de resumen final como líneas
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

        resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) +  ' - Shipper: ' + str(row.embarcador) + \
 \
                              '; Consignee: ' + str(row.consignatario)

        fecha_formateada = fecha_actual.strftime(
            f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')

        texto += fecha_formateada.capitalize().upper() + '<br><br>'
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        texto += formatear_linea("Embarque", str(row.seguimiento) if row.seguimiento else "S/I")

        texto += formatear_linea("Posición", str(row.posicion) if row.posicion else "S/I")

        texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))

        texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))

        texto += formatear_linea("Origen", str(origen.nombre) if origen else "S/I")

        texto += formatear_linea("Destino", str(destino.nombre) if destino else "S/I")

        texto += formatear_linea("Vuelo", str(vapor))

        texto += formatear_linea("H B/L", str(row.hawb) if row.hawb else "S/I")
        texto += formatear_linea("Embarcador", str(row.embarcador) if row.embarcador else "S/I")

        texto += formatear_linea("Consignatario", str(row.consignatario) if row.consignatario else "S/I")



        cont = 1

        for m in merca:
            texto += formatear_linea(f"Mercadería {cont}", str(m.nombre) if m.nombre else "S/I")

            cont += 1

        cont = 1

        for b in row2:
            texto += formatear_linea(f"Bultos {cont}", b.bultos if b.bultos is not None else "S/I")

            texto += formatear_linea(f"Peso {cont}", b.bruto if b.bruto is not None else "S/I")

            cont += 1
        texto += ('Los buques y las llegadas al puerto de Montevideo son siempre a CONFIRMAR, ya </br>'
                  ' que puede haber trasbordos y/o alteraciones en las fechas estimadas de llegada </br>'
                  'sin previo aviso, por lo cual sugerimos consultarnos por la fecha de arribo que aparece en este aviso.')
        texto += "<br>"

        return texto, resultado
    elif title == 'Routing Order':

        hora_actual = datetime.now().strftime("%H:%M")

        resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) + ' - Shipper: ' + str(row.embarcador) + \
                        \
                              '; Consignee: ' + str(row.consignatario)

        fecha_actual = datetime.now()

        texto = ""

        texto += formatear_linea("Hora", hora_actual)

        texto += formatear_linea("Fecha", format_fecha(fecha_actual))

        texto += formatear_linea("A", str(row.agente) if row.agente else "S/I")

        texto += formatear_linea("Departamento", "MARÍTIMO")

        texto += "<br>"

        texto += "Estimados Sres.:<br>"

        texto += "Por favor, contactar la siguiente compañía para coordinar la operación referenciada:<br><br>"

        # Proveedor

        texto += formatear_linea("Proveedor", str(row.embarcador) if row.embarcador else "S/I")

        texto += formatear_linea("Dirección", str(row.direccion_embarcador) if row.direccion_embarcador else "S/I")

        texto += formatear_linea("Ciudad", str(row.ciudad_embarcador) if row.ciudad_embarcador else "S/I")

        texto += formatear_linea("País", str(row.pais_embarcador) if row.pais_embarcador else "S/I")

        texto += "<br>"

        # Consignatario

        texto += formatear_linea("Consignatario", str(row.consignatario) if row.consignatario else "S/I")

        texto += formatear_linea("Dirección", str(row.direccion_consignatario) if row.direccion_consignatario else "S/I")

        texto += formatear_linea("Ciudad", str(row.ciudad_consignatario) if row.ciudad_consignatario else "S/I")

        texto += formatear_linea("País", str(row.pais_consignatario) if row.pais_consignatario else "S/I")

        texto += "<br>"

        # Detalles del embarque
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        texto += formatear_linea("Referencia interna", str(row_number) if row_number else "S/I")

        texto += formatear_linea("Orden Cliente", str(row.orden_cliente) if row.orden_cliente else "S/I")

        texto += formatear_linea("Origen", str(origen.nombre) if origen else "S/I")

        texto += formatear_linea("Destino", str(destino.nombre) if destino else "S/I")

        texto += "<br>"

        # Mercaderías y bultos

        cont = 1

        for m in merca:
            texto += formatear_linea(f"Mercadería {cont}", str(m.nombre) if m.nombre else "S/I")

            cont += 1

        cont = 1

        for b in row2:
            texto += formatear_linea(f"Bultos {cont}", b.bultos if b.bultos else "S/I")

            texto += formatear_linea(f"Peso {cont}", b.bruto if b.bruto else "S/I")

            cont += 1

        texto += "<br>"

        texto += formatear_linea("Condiciones de pago", str(row.pago_flete) if row.pago_flete else "S/I")

        texto += formatear_linea("Términos de compra", str(row.terminos) if row.terminos else "S/I")

        texto += formatear_linea("Modo de embarque", "MARÍTIMO")

        texto += "<br>"

        texto += "OCEANLINK<br>"

        return texto, resultado
    elif title == 'Notificación de llegada de carga':
        refcliente = seguimiento.refcliente if seguimiento.refcliente else "S/I"

        resultado[
            'asunto'] = f'NOTIFICACION DE LLEGADA DE CARGA - Ref.: {row.seguimiento} - HB/l: {row.hawb} - Ship: {row.embarcador} - Consig: {row.consignatario}; Vuelo: {vapor}; Ord. Cliente: {refcliente}'

        locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

        fecha_actual = datetime.now()

        fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

        consigna = Clientes.objects.get(codigo=embarque.consignatario)

        carga = ExportCargaaerea.objects.filter(numero=embarque.numero)

        gastos = ExportServiceaereo.objects.filter(numero=embarque.numero)
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        texto = formatear_linea("Fecha", fecha_formateada)

        texto += "<br>"

        texto += formatear_linea("Att.", "")

        texto += formatear_linea("Notificar a", row.consignatario)

        texto += formatear_linea("Dirección", consigna.direccion if consigna else "")

        texto += formatear_linea("Teléfono", consigna.telefono if consigna else "")

        texto += "<br>"

        texto += formatear_linea("Salida", row.etd.strftime('%d-%m-%Y') if row.etd else '')

        texto += formatear_linea("Llegada", row.eta.strftime('%d-%m-%Y') if row.eta else '')

        texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')

        texto += formatear_linea("Destino", destino.nombre if destino else 'S/I')

        texto += formatear_linea("HAWB", embarque.hawb)

        if master == 'true':
            texto += formatear_linea("AWB", row.awb)

        texto += formatear_linea("Referencia", row.seguimiento)


        texto += formatear_linea("Posición", embarque.posicion)

        texto += formatear_linea("Seguimiento", row.seguimiento)

        texto += formatear_linea("Embarcador", row.embarcador)

        texto += formatear_linea("Ref. Proveedor", row.embarcador)

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

                aplicable = round(ap1, 2) if ap1 > float(c.bruto) else float(c.bruto)

                texto += formatear_linea("Mercadería", c.producto.nombre)

                texto += formatear_linea("Bultos", str(c.bultos))

                texto += formatear_linea("Peso", str(c.bruto))

                texto += formatear_linea("Aplicable", str(aplicable))

            texto += "<br>"

        if gastos_boolean == 'true':

            if gastos:

                texto += '<p style="font-family: Courier New, monospace; font-size: 12px; line-height: 1;"> Detalle de gastos en Dólares U.S.A </p>'

                total_gastos = 0

                total_iva = 0

                for g in gastos:

                    servicio = Servicios.objects.get(codigo=g.servicio)

                    total_gastos += float(g.precio)

                    iva = servicio.tasa == 'B'

                    if iva:
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
        return texto,resultado
    elif title == 'Orden de facturacion':

        resultado['asunto'] = f'seguimiento: {row.seguimiento}'

        locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

        fecha_actual = datetime.now()

        fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

        if isinstance(seguimiento.eta, datetime):

            llegada = seguimiento.eta.strftime("%d/%m/%Y")

        else:

            llegada = ''

        texto = ""

        texto += formatear_linea("Fecha", fecha_formateada)

        texto += "<br>"

        texto += formatear_linea("Seguimiento", row.seguimiento)

        texto += formatear_linea("Posición", row.posicion)

        texto += formatear_linea("Master", row.awb)

        texto += formatear_linea("ETA", llegada)

        texto += formatear_linea("Cliente", seguimiento.cliente)

        texto += "<br>"

        texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

        texto += "OCEANLINK\n"

        texto += "</pre>"

        return texto, resultado
    elif title == 'Aviso de desconsolidacion':

        fecha_actual = datetime.now()

        fecha_formateada = fecha_actual.strftime(
            f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')

        resultado['asunto'] = (

            f'Ref.: {row.seguimiento}  - HB/l: {row.hawb} - Ship: {row.embarcador}'

        )
        try:
            consigna=Clientes.objects.get(codigo=row.consignatario_id)
            telefono=consigna.telefono
        except Clientes.DoesNotExist:
            telefono='S/I'


        texto += formatear_linea("Fecha", fecha_formateada.upper())

        texto += "<br>"

        texto += formatear_linea("Att.", "DEPARTAMENTO DE OPERACIONES")

        texto += formatear_linea("Consignatario", str(row.consignatario))

        texto += formatear_linea("Dirección", row.direccion_consignatario or "")

        texto += formatear_linea("Teléfono", telefono or "")


       # texto += formatear_linea("Vapor", row.vapor or "")  # cambiar esto

        texto += formatear_linea("Viaje", conex.viaje or "")

        if isinstance(conex.llegada, datetime):
            texto += formatear_linea("Llegada", conex.llegada.strftime("%d/%m/%Y"))

        texto += formatear_linea("Posición", row.posicion or "")

        texto += formatear_linea("Seguimiento", row.seguimiento)

        texto += formatear_linea("Embarcador", row.embarcador)

        #texto += formatear_linea("Consignatario", row.consignatario)

        texto += formatear_linea("Orden cliente", seguimiento.refcliente)

        texto += formatear_linea("Referencia proveedor", seguimiento.refproveedor)

        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')

        texto += formatear_linea("Destino", destino.nombre if origen else 'S/I')

        # Datos de contenedores

        cantidad_cntr = ""

        contenedores = ""

        precintos = ""

        movimiento = ""

        mercaderias = ""

        bultos = 0

        peso = 0

        volumen = 0

        cant_cntr = ExportCargaaerea.objects.filter(numero=row.numero).values(

            'bruto', 'nrocontenedor', 'medidas', 'bultos','producto__nombre').annotate(total=Count('id'))

        if cant_cntr.count() > 0:

            for cn in cant_cntr:
                contenedores += f' {cn["nrocontenedor"]} - '
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

        texto += formatear_linea("Nro. Contenedor/es", contenedores.strip(' -'))

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


def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
        return base64_data
