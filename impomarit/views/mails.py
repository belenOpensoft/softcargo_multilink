import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
import base64

from django.utils.autoreload import raise_last_exception
from django.views.decorators.csrf import csrf_exempt
from reportlab.lib.validators import isNumber

from cargosystem import settings
from impomarit.models import VEmbarqueaereo, Cargaaerea, Envases, Serviceaereo, VGastosHouse, Embarqueaereo, Conexaerea
from login.models import AccountEmail
from mantenimientos.models import Productos, Clientes, Monedas, Servicios, Vapores, Ciudades
from mantenimientos.views.bancos import is_ajax
import locale
from datetime import datetime
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
            master = request.POST['master']
            gastos_boolean = request.POST['gastos']
            directo_boolean = request.POST['directo']

            #9155
            embarque=Embarqueaereo.objects.get(numero=row_number)
            row = VEmbarqueaereo.objects.get(numero=row_number)
            row2 = Cargaaerea.objects.filter(numero=row_number)
            row3 = Envases.objects.filter(numero=row_number)
            gastos =VGastosHouse.objects.filter(numero=row_number)
            email_cliente = Clientes.objects.get(codigo=embarque.consignatario).emailim if embarque.consignatario is not None else 'S/I'
            email_agente = Clientes.objects.get(codigo=embarque.agente).emailim if embarque.agente is not None else 'S/I'

            if embarque.vapor is not None and embarque.vapor.isdigit():
                vapor = Vapores.objects.get(codigo=embarque.vapor).nombre
            elif embarque.vapor is not None:
                vapor = embarque.vapor
            else:
                vapor = 'S/I'

            try:
                seguimiento = VGrillaSeguimientos.objects.get(numero=row.seguimiento)
            except VGrillaSeguimientos.DoesNotExist:
                seguimiento = VGrillaSeguimientos(numero='', eta=None, etd=None, refcliente='',deposito='', pago='', vendedor='')

            texto = ''
            texto += f'<br>'
            texto, resultado = get_data_html(row_number, row, row2, row3, title, texto, resultado,seguimiento,gastos,embarque,transportista,master,gastos_boolean,vapor,directo_boolean,request)
            estilo = "font-family: Courier New, Courier, monospace; font-size: 12px;"
            texto += f"<div style='{estilo}'>Agradeciendo vuestra preferencia, le saludamos muy atentamente.</div></br>"
            texto += f"<div style='{estilo}'>{request.user.first_name} {request.user.last_name}</div>"
            texto += f"<div style='{estilo}'>{request.user.email}</div>"
            texto += f"<div style='{estilo}; font-weight: bold;'>DEPARTAMENTO DE IMPORT MARITIMO</div>"
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


def get_data_html(row_number, row, row2, row3, title, texto, resultado,seguimiento,gastos,embarque,transportista_boolean,master_boolean,gastos_boolean,vapor,directo_boolean,request):
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
                row.embarcador) + '- Consignee: ' + str(row.consignatario) + '- Vessel: '+str(vapor)

            fecha_formateada = fecha_actual.strftime(
                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y'
            )

            texto += fecha_formateada.capitalize().upper() + '<br><br>'

            # Bultos, peso y CBM agrupados
            if row2:
                bultos = [str(b.bultos) if b.bultos is not None else "S/I" for b in row2]
                pesos = [str(b.bruto) if b.bruto is not None else "S/I" for b in row2]
                cbms = [str(b.cbm) if b.cbm is not None else "S/I" for b in row2]

                texto += formatear_linea("Bultos", ", ".join(bultos))
                texto += formatear_linea("Peso", ", ".join(pesos))
                texto += formatear_linea("CBM", ", ".join(cbms))

            # Contenedores y precintos agrupados
            if row3:
                contenedores = [str(e.nrocontenedor) if e.nrocontenedor is not None else "S/I" for e in row3]
                precintos = [str(e.precinto) if e.precinto is not None else "S/I" for e in row3]

                texto += formatear_linea("Nro. Contenedores", ", ".join(contenedores))
                texto += formatear_linea("Precintos", ", ".join(precintos))

            # Datos generales
            texto += formatear_linea("Vapor", str(vapor))
            texto += formatear_linea("Viaje", str(row.viaje) if row.viaje is not None else "S/I")
            texto += formatear_linea("Llegada estimada", format_fecha(row.fecha_retiro))
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()

            texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")
            texto += formatear_linea("B/L", str(row.awb) if row.awb is not None else "S/I")
            texto += formatear_linea("H B/L", str(row.hawb) if row.hawb is not None else "S/I")
            texto += formatear_linea("Referencia", str(row_number) if row_number is not None else "S/I")
            texto += formatear_linea("Posición", str(row.posicion) if row.posicion is not None else "S/I")
            texto += formatear_linea("Seguimiento", str(row.seguimiento) if row.seguimiento is not None else "S/I")
            texto += formatear_linea("Consignatario",
                                     str(row.consignatario) if row.consignatario is not None else "S/I")
            texto += formatear_linea("Embarcador", str(row.embarcador) if row.embarcador is not None else "S/I")
            texto += formatear_linea("Orden cliente",
                                     str(row.orden_cliente) if row.orden_cliente is not None else "S/I")
            texto += formatear_linea("Ref. proveedor",
                                     str(row.ref_proveedor) if row.ref_proveedor is not None else "S/I")
            if merca:
                nombres_merc = [m.nombre if m.nombre else "S/I" for m in merca]
                texto += formatear_linea("Mercadería", ", ".join(nombres_merc))

            texto += "<br>"

            # Mini tabla como líneas
            texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")
            texto += formatear_linea("Destino", str(destino.nombre) if destino is not None else "S/I")
            texto += formatear_linea("Vapor/Vuelo", str(vapor))
            texto += formatear_linea("Viaje", str(row.viaje) if row.viaje is not None else "S/I")
            texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))
            texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))

            texto += "<br>"

            return texto, resultado
        elif title == 'Novedades sobre la carga':

            fecha_actual = datetime.now()

            resultado['asunto'] = 'Ref.: ' + str(row.seguimiento) +  '- Shipper: ' + str(row.embarcador) + \
     \
                                  '; Consignee: ' + str(row.consignatario)

            fecha_formateada = fecha_actual.strftime(

                f'{DIAS_SEMANA[fecha_actual.weekday()]}, %d de {MESES[fecha_actual.month - 1]} del %Y'

            )

            texto += fecha_formateada.capitalize().upper() + '<br><br>'


            # Datos generales
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()
            texto += formatear_linea("Embarque", str(row.seguimiento) if row.seguimiento is not None else "S/I")

            texto += formatear_linea("Posición", str(row.posicion) if row.posicion is not None else "S/I")

            texto += formatear_linea("Salida", format_fecha(row.fecha_embarque))

            texto += formatear_linea("Llegada", format_fecha(row.fecha_retiro))

            texto += formatear_linea("Origen", str(origen.nombre) if origen is not None else "S/I")

            texto += formatear_linea("Destino", str(destino.nombre) if destino is not None else "S/I")

            texto += formatear_linea("Vapor", str(vapor))

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
                cbms = [str(b.cbm) if b.cbm else "S/I" for b in row2]

                texto += formatear_linea("Bultos", ", ".join(bultos))
                texto += formatear_linea("Peso", ", ".join(pesos))
                texto += formatear_linea("CBM", ", ".join(cbms))

            # Contenedores y precintos
            if row3:
                contenedores = [str(e.nrocontenedor) if e.nrocontenedor else "S/I" for e in row3]
                precintos = [str(e.precinto) if e.precinto else "S/I" for e in row3]

                texto += formatear_linea("Nro. Contenedores", ", ".join(contenedores))
                texto += formatear_linea("Precintos", ", ".join(precintos))
            texto += ('Los buques y las llegadas al puerto de Montevideo son siempre a CONFIRMAR, ya </br>'
                      ' que puede haber trasbordos y/o alteraciones en las fechas estimadas de llegada </br>'
                      'sin previo aviso, por lo cual sugerimos consultarnos por la fecha de arribo que aparece en este aviso.')
            texto += "<br>"

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

            texto += formatear_linea("Ciudad", str(row.ciudad_consignatario) if row.ciudad_consignatario is not None else "S/I")

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

            # Fecha formateada

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

            consigna = Clientes.objects.get(codigo=embarque.consignatario)

            conex = Conexaerea.objects.filter(numero=embarque.numero).order_by('-id').last()

            carga = Cargaaerea.objects.filter(numero=embarque.numero)

            gastos = Serviceaereo.objects.filter(numero=embarque.numero)

            cant_cntr = Envases.objects.filter(numero=row.numero).values(

                'tipo', 'nrocontenedor', 'precinto', 'bultos', 'peso', 'unidad', 'volumen','movimiento'

            ).annotate(total=Count('id'))

            texto = formatear_linea("Fecha", fecha_formateada)

            texto += "<br>"

            texto += formatear_linea("Att.", "")

            texto += formatear_linea("Notificar a", row.consignatario)

            texto += formatear_linea("Dirección", consigna.direccion if consigna else "")

            texto += formatear_linea("Teléfono", consigna.telefono if consigna else "")

            texto += "<br>"
            salida = seguimiento.etd.strftime("%d/%m/%Y") if isinstance(seguimiento.etd, datetime) else ""

            llegada = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ""

            texto += formatear_linea("Salida", salida)

            texto += formatear_linea("Llegada", llegada)
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()

            texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')

            texto += formatear_linea("Destino", destino.nombre if destino else 'S/I')
            texto += formatear_linea("Vapor",vapor)

            texto += formatear_linea("HBL", embarque.hawb)

            if master_boolean == 'true':
                texto += formatear_linea("MBL", embarque.awb)

            texto += formatear_linea("Referencia", row.seguimiento)

            texto += formatear_linea("Posición", embarque.posicion)

            texto += formatear_linea("Seguimiento", row.seguimiento)

            texto += formatear_linea("Embarcador", row.embarcador)

            texto += formatear_linea("Ref. Proveedor", seguimiento.refproveedor)

            cantidad_cntr=contenedores=precintos=movimiento=''
            peso=volumen=bultos=0
            if cant_cntr.exists():

                for cn in cant_cntr:

                    cantidad_cntr += f'{cn["total"]} x {cn["unidad"]} - {cn["tipo"]} - '

                    contenedores += f'{cn["nrocontenedor"]} - '

                    if cn['precinto']:
                        precintos += f'{cn["precinto"]} - '

                    bultos += cn['bultos'] if cn['bultos'] else 0
                    peso += cn['peso'] if cn['peso'] else 0
                    volumen += cn['volumen'] if cn['volumen'] else 0
                    movimiento=cn['movimiento']

            texto += formatear_linea("Movimiento", movimiento)
            texto += formatear_linea("Contenedores", cantidad_cntr.rstrip(' -'))

            texto += formatear_linea("Nro. Contenedor/es", contenedores.rstrip(' -'))

            texto += formatear_linea("Precintos/Sellos", precintos.rstrip(' -'))


            if carga:

                for c in carga:
                    ap1 = float(c.cbm) if c.cbm is not None else 0
                    bruto = float(c.bruto) if c.bruto else 0
                    aplicable = round(ap1, 2) if ap1 >bruto else bruto

                    texto += formatear_linea("Mercadería", c.producto.nombre)

                    texto += formatear_linea("Bultos", str(c.bultos))

                    texto += formatear_linea("Peso", str(c.bruto))
                    if movimiento !='FCL/FCL':
                        texto += formatear_linea("Aplicable", str(aplicable))
                    texto += formatear_linea("CBM", str(ap1)+' M³')

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
                            texto += formatear_linea(servicio.nombre, f"{g.precio:.2f}",  1)

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
        elif title == 'Release documentacion':

            resultado['asunto'] = (

                f'FCR.: {row.hawb or ""} - SEGUIMIENTO {row.seguimiento or ""}'

            )

            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')  # Asegurate de que esté instalado el locale en tu sistema

            fecha_actual = datetime.now()

            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()

            texto = ""

            texto += formatear_linea("Fecha", fecha_formateada)

            texto += "<br>"

            texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

            texto += "Estimados,\n\n"

            texto += "Informamos a Uds. que se encuentra a vuestra disposición para ser retirada en nuestras oficinas\n"

            texto += "la documentación correspondiente a la liberación del siguiente embarque:\n\n"

            texto += f"{'FCR:':<20} {row.hawb or ''}\n"

            texto += f"{'BUQUE:':<20} {vapor or ''}\n\n"

            texto += "Favor presentar para dicha liberación los FCR correspondientes a este embarque.\n"

            texto += "Nuestro horario para transferencias es de lunes a viernes de 08:30 a 12:00 y de 13:00 a 16:30 hrs.\n\n"

            texto += "Saludos,\n\n"

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
                'asunto'] = f'Ref: {row.seguimiento} - HB/l: {row.hawb} - Shipper: {row.embarcador} - Consig: {row.consignatario}; Vapor: {vapor}; Ord. Cliente: {refcliente}'

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

            texto += formatear_linea("Proveedor", row.embarcador or "")
            texto += formatear_linea("Consignatario", row.consignatario or "")

            texto += formatear_linea("Orden Cliente", embarque.ordencliente or "")

            texto += formatear_linea("Ref. Proveedor", embarque.refproveedor or "")

            texto += formatear_linea("Términos de Compra", row.terminos or "")

            texto += formatear_linea("Vapor", vapor or "")

            texto += "<br>"
            # origen y destino nombre entero
            origen = Ciudades.objects.filter(codigo=row.origen).first()
            destino = Ciudades.objects.filter(codigo=row.destino).first()
            texto += formatear_linea("Origen", origen.nombre if origen else 'S/I')

            texto += formatear_linea("Destino", destino.nombre if destino else 'S/I')

            texto += formatear_linea("Salida", salida)

            texto += formatear_linea("Llegada", llegada)

            texto += "<br>"

            texto += formatear_linea("Agente", row.agente or "")

            # Datos de contenedores

            cantidad_cntr = ""

            contenedores = ""

            mercaderias = ""

            precintos = ""

            bultos = 0

            peso = 0

            volumen = 0

            cant_cntr = Envases.objects.filter(numero=row.numero).values(

                'tipo', 'nrocontenedor', 'precinto', 'bultos', 'peso', 'unidad', 'volumen'

            ).annotate(total=Count('id'))

            carga = Cargaaerea.objects.filter(numero=row.numero).values('producto__nombre','tipo')

            if cant_cntr.exists():

                for cn in cant_cntr:

                    cantidad_cntr += f'{cn["total"]} x {cn["unidad"]} - {cn["tipo"]} - '

                    contenedores += f'{cn["nrocontenedor"]} - '

                    if cn['precinto']:
                        precintos += f'{cn["precinto"]} - '

                    bultos += cn['bultos'] if cn['bultos'] else 0

                    peso += cn['peso'] if cn['peso'] else 0
                    volumen += cn['volumen'] if cn['volumen'] else 0

            if carga.exists():

                for c in carga:
                    mercaderias += c['producto__nombre'] + ' - '
                    tipo = c["tipo"]

            texto += formatear_linea("Contenedores", cantidad_cntr.rstrip(' -'))

            texto += formatear_linea("Nro. Contenedor/es", contenedores.rstrip(' -'))

            texto += formatear_linea("Precintos/Sellos", precintos.rstrip(' -'))

            texto += formatear_linea("HBL", row.hawb or "")

            if master_boolean == 'true':
                texto += formatear_linea("MBL", row.awb or "")

            if transportista_boolean == 'true':
                texto += formatear_linea("Transportista", row.transportista or "")

            texto += formatear_linea("Peso", f"{peso} KGS",)

            texto += formatear_linea("Bultos", str(bultos) + ' ' + str(tipo))

            texto += formatear_linea("CBM", f"{volumen:.3f} M³")

            texto += "<br>"

            texto += formatear_linea("Mercadería", mercaderias.rstrip(' -'))

            texto += formatear_linea("Depósito", seguimiento.deposito or "")


            texto += "<br>"
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

                        servicio = Servicios.objects.filter(codigo=codigo).first()
                        if servicio is not None:

                            if g.precio != 0 and g.precio is not None:
                                total_gastos += float(g.precio)
                            elif g.costo is not None and g.costo != 0:
                                total_gastos += float(g.costo)
                            else:
                                total_gastos += 0

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
            texto += "<tr>"
            texto += f"<td style='padding: 2px 10px;'>{row.origen or ''}</td>"
            texto += f"<td style='padding: 2px 10px;'>{row.destino or ''}</td>"
            texto += f"<td style='padding: 2px 10px;'>{str(vapor) or ''}</td>"
            texto += f"<td style='padding: 2px 10px;'>{str(row.viaje) or ''}</td>"
            texto += f"<td style='padding: 2px 10px;'>{salida}</td>"
            texto += f"<td style='padding: 2px 10px;'>{llegada}</td>"
            texto += "</tr>"

            texto += "</table><br>"

            # Mensaje final

            texto += "<pre style='font-family: Courier New, monospace; font-size: 12px;'>"

            texto += "Los buques y las llegadas al puerto de Montevideo son siempre a CONFIRMAR, ya que puede haber trasbordos y/o alteraciones en las fechas estimadas de llegada\n"
            texto += "sin previo aviso, por lo cual le sugerimos consultarnos por la fecha de arribo que aparece en este aviso.\n"
            texto += "</pre>"
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

                f'Ref.: {row.seguimiento} - HB/l: {row.hawb} - Ship: {row.embarcador}'


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

            mercaderias = Cargaaerea.objects.filter(numero=row.numero).values('producto__nombre')

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

            mercaderia = ''
            if mercaderias:
                for m in mercaderias:
                    mercaderia += str(m['producto__nombre']) + '-'

            #texto += formatear_linea("Contenedores", cantidad_cntr.strip(' -'))

            texto += formatear_linea("Nro. Contenedor/es", contenedores.strip(' -'))

            texto += formatear_linea("Precintos/sellos", precintos.strip(' -'))

            texto += formatear_linea("Bultos", str(bultos))

            texto += formatear_linea("Peso", f"{peso} KGS")

            texto += formatear_linea("CBM", f"{volumen} M³")

            texto += formatear_linea("Mercadería", mercaderia)

            texto += formatear_linea("Depósito", str(seguimiento.deposito))
            texto += formatear_linea("WR", str(seguimiento.wreceipt))

            texto += "<br>"

            texto += "<b>ATENCION!</b><br><br>"

            texto += "DETALLE DE DESCONSOLIDACION<br><br>"
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

            #hacer de nuevo
        elif title == 'Shipping instruction':

            #shipper = Clientes.objects.get(codigo=embarque.embarcador)

            consignee = Clientes.objects.get(codigo=embarque.consignatario)

            client = Clientes.objects.get(codigo=embarque.cliente)
            agente = Clientes.objects.get(codigo=embarque.agente)

            cargo_items = Cargaaerea.objects.filter(numero=row.numero)

            currency = Monedas.objects.get(codigo=embarque.moneda)

            containers = Envases.objects.filter(numero=row.numero)
            ocean = Clientes.objects.get(codigo=835)

            try:

                if embarque.embarcador:

                    supplier = Clientes.objects.get(codigo=embarque.embarcador)

                    address = supplier.direccion

                    company = supplier.empresa

                    city = supplier.ciudad

                    country = supplier.pais

                    email = supplier.emailim

                    contacts = supplier.contactos

                else:

                    address = company = city = country = contacts = email = ''

            except Clientes.DoesNotExist:

                address = company = city = country = contacts = email = ''

            resultado[
                'asunto'] = f'SHIPPING INSTRUCTION - Ref.: {seguimiento.numero} - Shipper: {company} - Consignee: {consignee.empresa}'

            locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')

            current_date = datetime.now()

            formatted_date = current_date.strftime('%A, %B %d, %Y').upper()

            eta = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ''

            full_name = str(request.user.first_name) + ' ' + str(request.user.last_name)

            texto = ''

            texto += formatear_linea("Date", formatted_date)

            texto += formatear_linea("To", agente.empresa)

            texto += formatear_linea("Department", "SEAFREIGHT")

            texto += formatear_linea("Sent by", full_name)

            texto += "<br><p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Dear colleagues:</p>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Please contact the following company to coordinate the following shipment as per our instructions below:</p>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Please ack this message and let us know status of cargo asap.</p><br>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Please add HS code on MBL an HBL</p><br>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>MBL -</p>"
                texto_ocean = str(ocean.empresa) + ' ' + str(ocean.direccion) + ' ' + 'CP 11000 ' + str(
                    ocean.ruc) + ' ' + str(ocean.telefono)
                texto += formatear_linea("Shipper", agente.empresa)
                texto += formatear_linea("Consignee", texto_ocean)
            texto+='</br>'
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>{'HBL' if directo_boolean == 'true' else 'MBL'}</p>"

            texto += formatear_linea("Shipper name", company)

            texto += formatear_linea("Address", address)

            texto += formatear_linea("City", city)

            texto += formatear_linea("Country", country)

            texto += formatear_linea("E-mail", email)

            texto += formatear_linea("Contacts", contacts)

            texto += "<br>"

            texto += formatear_linea("Consignee name", consignee.empresa)

            texto += formatear_linea("Address", consignee.direccion)

            texto += formatear_linea("Country", consignee.pais)

            texto += formatear_linea("Tax ID", consignee.ruc)

            texto += formatear_linea("Phone", consignee.telefono)

            texto += "<br>"

            texto += formatear_linea("Internal Reference", f"{seguimiento.numero}")

            texto += formatear_linea("Position", row.posicion)

            texto += formatear_linea("Estimated delivery date", eta)

            loading = 'S/I'
            discharge = 'S/I'

            if embarque.loading is not None:
                ciudad_l = Ciudades.objects.filter(codigo=embarque.loading).first()
                loading = ciudad_l.nombre
            if embarque.discharge is not None:
                ciudad_d = Ciudades.objects.filter(codigo=embarque.discharge).first()
                discharge = ciudad_d.nombre

            texto += formatear_linea("Port of loading", loading)

            texto += formatear_linea("Port of discharge", discharge)

            texto += "<br>"

            for item in cargo_items:
                volume = item.cbm if item.cbm else 0

                weight = item.bruto if item.bruto else 0

                tons = round(weight / 1000, 2)

                chargeable_weight = f"{round(volume,2)} AS VOL" if tons < volume else round(weight,2)

                texto += formatear_linea("Commodity", item.producto)

                texto += formatear_linea("Pieces", item.bultos)

                texto += formatear_linea("Weight", f"{round(item.bruto,2)} KGS")

                #texto += formatear_linea("Chargeable weight", chargeable_weight)

                texto += formatear_linea("Volume", f"{round(item.cbm,2)} CBM")

            payment_condition = "Collect" if row.pago_flete == "C" else "Prepaid" if row.pago_flete == "P" else ""

            texto += formatear_linea("Payment condition", payment_condition)

            texto += formatear_linea("Terms of purchase", row.terminos)

            if transportista_boolean == 'true':
                texto += formatear_linea("Carrier", row.transportista)

            texto += formatear_linea("Transport contract", seguimiento.contratotra)

            texto += formatear_linea("Mode of shipment", "MARITIME")

            texto += formatear_linea("Currency", currency.nombre)

            texto += "<br>"
        elif title == 'Instruccion de embarque':
            #embarcador = Clientes.objects.get(codigo=embarque.embarcador)
            consignatario = Clientes.objects.get(codigo=embarque.consignatario)
            cliente = Clientes.objects.get(codigo=embarque.cliente)
            agente = Clientes.objects.get(codigo=embarque.agente)
            mercaderia = Cargaaerea.objects.filter(numero=row.numero)
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
                    direccion = empresa = ciudad = pais = contactos=email=''
            except Clientes.DoesNotExist:
                direccion = empresa = ciudad = pais = contactos = email = ''

            resultado[
                'asunto'] = f'INSTRUCCIÓN DE EMBARQUE - Ref.: {seguimiento.numero} - Shipper: {empresa} - Consignee: {consignatario.empresa}'
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
            fecha_actual = datetime.now()
            fecha_formateada = fecha_actual.strftime('%A, %d de %B del %Y').upper()
            llegada = seguimiento.eta.strftime("%d/%m/%Y") if isinstance(seguimiento.eta, datetime) else ''
            nombre = str(request.user.first_name) + ' ' + str(request.user.last_name)

            texto = ''
            texto += formatear_linea("Fecha", fecha_formateada)
            texto += formatear_linea("A", agente.empresa)
            texto += formatear_linea("Departamento", "MARITIMO")
            texto += formatear_linea("Envíado", nombre)

            texto += "<br><p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Estimados Sres.:</p><br>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Por favor, contactar a la siguiente compañía para coordinar el siguiente embarque según nuestras instrucciones a continuación:</p>"
            texto += "<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Por favor confirmar este mensaje e informarnos el estado de la carga a la brevedad.</p><br>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>Favor incluir el código HS en MBL y HBL</p>"
            if directo_boolean == 'true':
                texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>MBL -</p>"
                ocean = Clientes.objects.get(codigo=835)
                texto_ocean = str(ocean.empresa) + ' ' + str(ocean.direccion) + ' CP 11000 ' + str(
                    ocean.ruc) + ' ' + str(ocean.telefono)
                texto += formatear_linea("Shipper", agente.empresa)
                texto += formatear_linea("Consignatario", texto_ocean)
            texto += "<br>"
            texto += f"<p style='font-family: Courier New, Courier, monospace; font-size: 12px;'>{'MBL' if directo_boolean == 'true' else 'HBL'}</p>"

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
            loading = 'S/I'
            discharge = 'S/I'

            if embarque.loading is not None:
                ciudad_l = Ciudades.objects.filter(codigo=embarque.loading).first()
                loading = ciudad_l.nombre
            if embarque.discharge is not None:
                ciudad_d = Ciudades.objects.filter(codigo=embarque.discharge).first()
                discharge = ciudad_d.nombre

            texto += formatear_linea("Puerto de carga", loading)
            texto += formatear_linea("Puerto de descarga", discharge)


            texto += "<br>"
            for m in mercaderia:
                vol = m.cbm if m.cbm else 0
                pes = m.bruto if m.bruto else 0

                toneladas = round(pes / 1000, 2)
                calculado2 = f"{round(vol,2)} AS VOL" if toneladas < vol else round(pes,2)


                texto += formatear_linea("Mercadería", m.producto)
                texto += formatear_linea("Bultos", m.bultos)
                texto += formatear_linea("Peso", f"{round(pes,2)} KGS")
               # texto += formatear_linea("Aplicable", calculado2)
                texto += formatear_linea("Volumen", f"{round(vol,2)} CBM")


            condicion_pago = "Collect" if row.pago_flete == "C" else "Prepaid" if row.pago_flete == "P" else ""
            texto += formatear_linea("Condiciones de pago", condicion_pago)
            texto += formatear_linea("Términos de compra", row.terminos)
            if transportista_boolean == 'true':
                texto += formatear_linea("Transportista", row.transportista)
            texto += formatear_linea("Contrato transport.", seguimiento.contratotra)
            texto += formatear_linea("Modo de Embarque", "MARITIMO")
            texto += formatear_linea("Moneda", moneda.nombre if moneda is not None else 'S/I' )
            texto += "<br>"
        return texto, resultado
    except Exception as e:
        raise TypeError(e)


def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
        return base64_data



def formatear_linea_old(titulo, valor, ancho_total=110, ancho_col_izq=25):
    """
    Formatea una línea con estilo tipo factura o instrucción de embarque,
    usando puntos y dos columnas al estilo:
    Título ......... : Valor
    """
    puntos = '.' * (ancho_col_izq - len(titulo))
    col_izq = f"{titulo} {puntos} :"
    return f"<div style='font-family: Courier New, monospace; font-size: 12px; line-height: 1;'>{col_izq} {valor}</div>"

def formatear_linea(titulo, valor, alinear_derecha=None, ancho_total=110, ancho_col_izq=25):
    """
    Formatea una línea con estilo tipo factura o instrucción de embarque,
    usando puntos y dos columnas al estilo:
    Título ......... : Valor
    Si alinear_derecha es True o no es None, alinea el valor a la derecha dentro del contenedor.
    """
    puntos = '.' * max(ancho_col_izq - len(titulo), 0)
    col_izq = f"{titulo} {puntos} :"

    return f"""
        <div style='font-family: Courier New, monospace; font-size: 12px; line-height: 1; display: flex; justify-content: space-between; max-width: 50ch;'>
            <span>{col_izq}</span>
            <span>{valor}</span>
        </div>
    """ if alinear_derecha else f"""
        <div style='font-family: Courier New, monospace; font-size: 12px; line-height: 1;'>
            {col_izq} {valor}
        </div>
    """


def formatear_caratula_old(titulo, valor):
    return f"<div style='font-family: Courier New, monospace; font-size: 11.5px; line-height: 1;'>{titulo}: {valor}</div>"


def formatear_caratula(titulo, valor):
    valor = valor or 'S/I'
    return f"<div style='font-family: Courier New, monospace; font-size: 11.5px; line-height: 1;'>{titulo}: {valor}</div>"



