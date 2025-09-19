import locale
from datetime import datetime
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
import base64
from django.views.decorators.csrf import csrf_exempt

from cargosystem import settings
from expmarit.models import VEmbarqueaereo, ExpmaritCargaaerea as Cargaaerea, ExpmaritEnvases as Envases, \
    ExpmaritServiceaereo as Serviceaereo, ExpmaritEmbarqueaereo as Embarqueaereo, ExpmaritConexaerea as Conexaerea
from impomarit.views.mails import formatear_linea
from login.models import AccountEmail
from mantenimientos.views.bancos import is_ajax
from mantenimientos.models import Productos, Clientes, Monedas, Servicios, Vapores, Ciudades
from seguimientos .models import VGrillaSeguimientos

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
            row = VEmbarqueaereo.objects.get(numero=row_number)
            row2 = Cargaaerea.objects.filter(numero=row_number)
            row3 = Envases.objects.filter(numero=row_number)
            embarque=Embarqueaereo.objects.get(numero=row_number)
            gastos = Serviceaereo.objects.filter(numero=row_number)
            email_cliente = Clientes.objects.get(codigo=embarque.consignatario).emailem if embarque.consignatario is not None else 'S/I'
            email_agente = Clientes.objects.get(codigo=embarque.agente).emailem if embarque.agente is not None else 'S/I'

            if embarque.vapor is not None and embarque.vapor.isdigit():
                vapor = Vapores.objects.get(codigo=embarque.vapor).nombre
            elif embarque.vapor is not None:
                vapor = embarque.vapor
            else:
                vapor = 'S/I'


            try:
                seguimiento = VGrillaSeguimientos.objects.get(numero=row.seguimiento)

            except VGrillaSeguimientos.DoesNotExist:

                seguimiento = VGrillaSeguimientos(numero='', eta=None, etd=None, refcliente='', deposito='', pago='',vendedor='')

            texto = ''
            texto += f'<br>'
            texto, resultado = get_data_html(row_number, row, row2, row3, title, texto, resultado,seguimiento,gastos,embarque,master,gastos_boolean,vapor,request)
            estilo = "font-family: Courier New, Courier, monospace; font-size: 12px;"
            texto += f"<div style='{estilo}'>Agradeciendo vuestra preferencia, le saludamos muy atentamente.</div></br>"
            texto += f"<div style='{estilo}'>{request.user.first_name} {request.user.last_name}</div>"
            texto += f"<div style='{estilo}'>{request.user.email}</div>"
            texto += f"<div style='{estilo}; font-weight: bold;'>DEPARTAMENTO DE EXPORT MARITIMO</div>"
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



def get_data_html(row_number, row, row2, row3, title, texto, resultado, seguimiento,gastos,embarque,master,gastos_boolean,vapor,request):
    # merca = Productos.objects.get(codigo=row2.producto.codigo)
    if row2 is not None:
        merca = []
        for m in row2:
            merca.append(m.producto)

    fecha_actual = datetime.now()

    if title == 'Notificación de transbordo de carga':
        fecha_actual = datetime.now()

        resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) + '- H B/L: ' + str(row.hawb) + '- Shipper: ' + str(
            row.embarcador) + '- Consignee: ' + str(row.consignatario) + '- Vessel: '+str(vapor)

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

        # Contenedores
        cont = 1
        for e in row3:
            texto += formatear_linea(f"Nro. Contenedor {cont}", str(e.nrocontenedor) if e.nrocontenedor else "S/I")
            cont += 1

        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        # Datos generales
        texto += formatear_linea("Vapor", str(vapor) if vapor is not None else "S/I")
        texto += formatear_linea("Viaje", str(row.viaje) if row.viaje is not None else "S/I")
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

        # Mini resumen
        texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")
        texto += formatear_linea("Destino", str(destino.nombre) if destino is not None else "S/I")
        texto += formatear_linea("Vapor/Vuelo", str(vapor) if vapor is not None else "S/I")
        texto += formatear_linea("Viaje", str(row.viaje) if row.viaje is not None else "S/I")
        texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))
        texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))

        texto += "<br>"

        return texto, resultado
    elif title == 'Novedades sobre la carga':

        fecha_actual = datetime.now()

        resultado['asunto'] = ( 'Ref.: ' + str(row.seguimiento) + ' - Shipper: ' + str(row.embarcador) +

                '; Consignee: ' + str(row.consignatario)
        )

        fecha_formateada = fecha_actual.strftime(

            f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y'

        )

        texto += fecha_formateada.capitalize().upper() + '<br><br>'


        # Datos generales
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        texto += formatear_linea("Embarque", row.seguimiento if row.seguimiento else "S/I")

        texto += formatear_linea("Posición", row.posicion if row.posicion else "S/I")

        texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))

        texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))

        texto += formatear_linea("Origen", origen.nombre if origen else "S/I")

        texto += formatear_linea("Destino", destino.nombre if destino else "S/I")

        texto += formatear_linea("Vapor", vapor if vapor else "S/I")

        texto += formatear_linea("H B/L", row.hawb if row.hawb else "S/I")
        texto += formatear_linea("Embarcador", row.embarcador if row.embarcador else "S/I")

        texto += formatear_linea("Consignatario", row.consignatario if row.consignatario else "S/I")


        # Mercadería
        # Mercaderías
        if merca:
            nombres_merc = [m.nombre if m.nombre else "S/I" for m in merca]
            texto += formatear_linea("Mercadería", ", ".join(nombres_merc))

        # Bultos / Peso / CBM

        if row2:
            bultos = [str(b.bultos) if b.bultos else "S/I" for b in row2]
            pesos = [str(round(float(b.bruto or 0),2)) if b.bruto else "S/I" for b in row2]
            cbms = [str(round(float(b.cbm or 0),2)) if b.cbm else "S/I" for b in row2]

            texto += formatear_linea("Bultos", ", ".join(bultos))
            texto += formatear_linea("Peso", ", ".join(pesos))
            texto += formatear_linea("CBM", ", ".join(cbms))

        # Contenedores y precintos
        if row3:
                contenedores = [str(e.nrocontenedor) if e.nrocontenedor else "S/I" for e in row3]
                precintos = [str(e.precinto) if e.precinto else "S/I" for e in row3]

                texto += formatear_linea("Nro. Contenedores", ", ".join(contenedores))
                texto += formatear_linea("Precintos", ", ".join(precintos))
        # Despedida

        texto += ('Los buques y las llegadas al puerto de Montevideo son siempre a CONFIRMAR, ya </br>'
                  ' que puede haber trasbordos y/o alteraciones en las fechas estimadas de llegada </br>'
                  'sin previo aviso, por lo cual sugerimos consultarnos por la fecha de arribo que aparece en este aviso.')

        return texto, resultado
    elif title == 'Routing Order':

        hora_actual = datetime.now().strftime("%H:%M")

        fecha_actual = datetime.now()

        resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) +  '- Shipper: ' + str(row.embarcador) + \
 \
                              '; Consignee: ' + str(row.consignatario)

        texto += f'{hora_actual} <br><br>'

        # Encabezado

        texto += formatear_linea("Fecha", format_fecha(fecha_actual))

        texto += formatear_linea("A", str(row.agente) if row.agente is not None else "S/I")

        texto += formatear_linea("Departamento", "MARITIMO")

        texto += '<br><br>Estimados Sres.: <br>'

        texto += 'Por favor, contactar la siguiente compañía para coordinar la operación referenciada: <br><br>'

        # Embarcador

        texto += formatear_linea("Proveedor", str(row.embarcador) if row.embarcador is not None else "S/I")

        texto += formatear_linea("Dirección",
                                 str(row.direccion_embarcador) if row.direccion_embarcador is not None else "S/I")

        texto += formatear_linea("Ciudad", str(row.ciudad_embarcador) if row.ciudad_embarcador is not None else "S/I")

        texto += formatear_linea("País", str(row.pais_embarcador) if row.pais_embarcador is not None else "S/I")

        texto += '<br>'

        # Consignatario

        texto += formatear_linea("Consignatario", str(row.consignatario) if row.consignatario is not None else "S/I")

        texto += formatear_linea("Dirección",
                                 str(row.direccion_consignatario) if row.direccion_consignatario is not None else "S/I")

        texto += formatear_linea("Ciudad",
                                 str(row.ciudad_consignatario) if row.ciudad_consignatario is not None else "S/I")

        texto += formatear_linea("País", str(row.pais_consignatario) if row.pais_consignatario is not None else "S/I")

        texto += '<br>'

        # Datos generales
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()

        texto += formatear_linea("Referencia interna", str(row_number) if row_number is not None else "S/I")

        texto += formatear_linea("Orden cliente", str(row.orden_cliente) if row.orden_cliente is not None else "S/I")

        texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")

        texto += formatear_linea("Destino", str(destino.nombre) if destino is not None else "S/I")

        texto += '<br>'

        # Mercadería y bultos/peso

        cont = 1

        for m in merca:
            texto += formatear_linea(f"Mercadería {cont}", str(m.nombre) if m.nombre is not None else "S/I")

            cont += 1

        cont = 1

        for b in row2:
            texto += formatear_linea(f"Bultos {cont}", b.bultos if b.bultos is not None else "S/I")

            texto += formatear_linea(f"Peso {cont}", b.bruto if b.bruto is not None else "S/I")

            cont += 1

        texto += formatear_linea("Condiciones de pago", str(row.pago_flete) if row.pago_flete is not None else "S/I")

        texto += formatear_linea("Términos de compra", str(row.terminos) if row.terminos is not None else "S/I")

        texto += formatear_linea("Modo de embarque", "MARITIMO")

        texto += "<br>"

        return texto, resultado
    elif title == 'Notificación de llegada de carga':
        refcliente = seguimiento.refcliente if seguimiento.refcliente else "S/I"

        resultado[
            'asunto'] = f'NOTIFICACION DE LLEGADA DE CARGA - Ref.: {row.seguimiento} - HB/l: {row.hawb} - Ship: {row.embarcador} - Consig: {row.consignatario}; Vapor: {vapor}; Ord. Cliente: {refcliente}'

        # Fecha actual en español

        locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

        fecha_actual = datetime.now()

        fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

        consigna = Clientes.objects.get(codigo=embarque.consignatario)

        conex = Conexaerea.objects.filter(numero=embarque.numero).order_by('-id').last()

        carga = Cargaaerea.objects.filter(numero=embarque.numero)

        gastos = Serviceaereo.objects.filter(numero=embarque.numero)

        texto = formatear_linea("Fecha", fecha_formateada)

        texto += "<br>"

        texto += formatear_linea("Att.", "")

        texto += formatear_linea("Notificar a", row.consignatario)

        texto += formatear_linea("Dirección", consigna.direccion if consigna else "")

        texto += formatear_linea("Teléfono", consigna.telefono if consigna else "")

        texto += "<br>"
        # origen y destino nombre entero
        origen = Ciudades.objects.filter(codigo=row.origen).first()
        destino = Ciudades.objects.filter(codigo=row.destino).first()
        texto += formatear_linea("Salida", row.etd.strftime('%d-%m-%Y') if row.etd else '')

        texto += formatear_linea("Llegada", row.eta.strftime('%d-%m-%Y') if row.eta else '')

        texto += formatear_linea("Origen", origen.nombre if origen else 'S/I' )

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
                ap1 = float(c.cbm) if c.cbm is not None else 0

                aplicable = round(ap1, 2) if ap1 > float(c.bruto) else float(c.bruto)

                texto += formatear_linea("Mercadería", c.producto.nombre)

                texto += formatear_linea("Bultos", str(c.bultos))

                texto += formatear_linea("Peso", str(c.bruto))

                #texto += formatear_linea("Aplicable", str(aplicable))

            texto += "<br>"

        if gastos_boolean == 'true' and gastos:

            texto += formatear_linea("Detalle", "Gastos en Dólares U.S.A")

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
    elif title == 'Aviso de desconsolidacion':

        fecha_actual = datetime.now()
        conex = Conexaerea.objects.filter(numero=embarque.numero).order_by('-id').last()

        fecha_formateada = fecha_actual.strftime(
            f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y')
        try:
            consigna=Clientes.objects.get(codigo=row.consignatario_id)
            telefono=consigna.telefono
        except Clientes.DoesNotExist:
            telefono='S/I'

        resultado['asunto'] = (

            f' Ref.: {row.seguimiento} - HB/l: {row.hawb} - Ship: {row.embarcador}'


        )

        texto += formatear_linea("Fecha", fecha_formateada.upper())

        texto += "<br>"

        texto += formatear_linea("Att.", "DEPARTAMENTO DE OPERACIONES")

        texto += formatear_linea("Cliente", str(row.consignatario))

        texto += formatear_linea("Dirección", row.direccion_consignatario or "")

        texto += formatear_linea("Teléfono", telefono or "")

        if row.vapor is not None and row.vapor.isdigit():
            vapor = Vapores.objects.get(codigo=row.vapor).nombre
        elif row.vapor is not None:
            vapor = row.vapor
        else:
            vapor = 'S/I'

        texto += formatear_linea("Vapor", vapor or "")  # cambiar esto

        texto += formatear_linea("Viaje", conex.viaje or "")

        if isinstance(conex.llegada, datetime):
            texto += formatear_linea("Llegada", conex.llegada.strftime("%d/%m/%Y"))

        texto += formatear_linea("Posición", row.posicion or "")

        texto += formatear_linea("Seguimiento", row.seguimiento)

        texto += formatear_linea("Embarcador", row.embarcador)

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

        cant_cntr = Envases.objects.filter(numero=row.numero).values(

            'tipo', 'nrocontenedor', 'precinto', 'bultos',

            'peso', 'envase', 'movimiento', 'volumen'

        ).annotate(total=Count('id'))

        if cant_cntr.count() > 0:

            for cn in cant_cntr:

                cantidad_cntr += f' {cn["total"]} x {cn["tipo"]} - '

                contenedores += f' {cn["nrocontenedor"]} - '

                if cn['precinto']:
                    precintos += f'{cn["precinto"]} - '

                bultos += cn['bultos'] if cn['bultos'] else 0

                if cn['peso']:
                    peso += cn['peso']

                if cn['volumen']:
                    volumen += cn['volumen']

                movimiento += f'{cn["movimiento"]} - '

                mercaderias += f'{cn["envase"]} - '

        texto += formatear_linea("Contenedores", cantidad_cntr.strip(' -'))

        texto += formatear_linea("Nro. Contenedor/es", contenedores.strip(' -'))

        texto += formatear_linea("Precintos/sellos", precintos.strip(' -'))

        texto += formatear_linea("Bultos", str(bultos))

        texto += formatear_linea("Peso", f"{peso} KGS")

        texto += formatear_linea("CBM", f"{volumen} M³")

        texto += formatear_linea("Mercadería", mercaderias.strip(' -'))

        texto += formatear_linea("Depósito", str(seguimiento.deposito))
        texto += formatear_linea("WR", str(seguimiento.wreceipt))

        texto += "<br>"

        texto += "<b>ATENCION!</b><br><br>"

        texto += "DETALLE DE DESCONSOLIDACION<br><br>"
    return texto, resultado



def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
        return base64_data
