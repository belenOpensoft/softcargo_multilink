import datetime
import json
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from mantenimientos.models import Clientes as MantenimientosClientes, Ciudades as MantenimientosCiudades
from impomarit.views.mails import formatear_caratula
from mantenimientos.models import Vapores
from mantenimientos.views.bancos import is_ajax
from seguimientos.models import VGrillaSeguimientos, Envases, VCargaaerea, Cargaaerea, Conexaerea


@login_required(login_url='/')
def get_datos_caratula(request):
    resultado = {}
    if is_ajax(request):
        try:
            id = request.POST['numero']
            row = VGrillaSeguimientos.objects.get(numero=id)
            aereo = row.modo in ['IMPORT AEREO', 'EXPORT AEREO']

            texto = '<div style="margin: 0 auto; font-family: Courier New, monospace; font-size: 11.5px;">'
            texto += '<h2 style="text-align: left;">OCEANLINK LTDA.</h2>'
            texto += '<b><p style="font-size:17px;text-align:right; word-wrap: break-word; white-space: normal; max-width: 100%; margin-right:60px;">'
            texto += f'Seguimiento: {row.numero}<br>'
            texto += f'Posicion:  {row.posicion or ""}<br>'
            texto += f'Incoterms: {row.terminos or ""}</p></b>'
            texto += '<p style="text-align:right; word-wrap: break-word; white-space: normal; max-width: 100%; margin-right:60px;">'
            texto += f'Origen: {row.origen or ""}<br>'
            texto += f'Destino:  {row.destino or ""}</p><br>'

            texto += formatear_caratula("Master", row.awb or "")
            texto += formatear_caratula("House", row.hawb or "")
            texto += formatear_caratula("ETA", row.eta.strftime('%d-%m-%Y') if isinstance(row.eta, datetime.datetime) else "?")
            texto += formatear_caratula("ETD", row.etd.strftime('%d-%m-%Y') if isinstance(row.etd, datetime.datetime) else "?")

            if aereo:
                vapor = Conexaerea.objects.filter(numero=row.numero).values_list('vapor', flat=True).first()
                nombre_vapor = vapor or 'S/I'
                texto += formatear_caratula("Vuelo", nombre_vapor)
            else:
                if isinstance(row.vapor, int) or (isinstance(row.vapor, str) and row.vapor.isdigit()):
                    vapor_obj = Vapores.objects.filter(codigo=int(row.vapor)).first()
                    nombre_vapor = vapor_obj.nombre if vapor_obj else 'S/I'
                else:
                    nombre_vapor = row.vapor or 'S/I'
                texto += formatear_caratula("Vapor", nombre_vapor)

            texto += formatear_caratula("Transportista", row.transportista or "")
            texto += formatear_caratula("Orden cliente", row.refcliente or "S/O")
            texto += '<br><span style="display: block; border-top: 0.2pt solid #CCC; margin: 2px 0;"></span><br>'

            # Embarcador
            emb = MantenimientosClientes.objects.filter(codigo=row.embarcador_codigo).first()
            if emb:
                emb_ciudad = MantenimientosCiudades.objects.filter(codedi=emb.ciudad).first()
                direccion_emb = f"{emb.direccion} - {emb_ciudad.nombre if emb_ciudad else 'S/I'} - {emb.pais}"
                texto += f"<b>Embarcador: {emb.empresa}</b><br>"
                texto += "<b>Datos del embarcador:</b><br>"
                texto += formatear_caratula("Empresa", emb.empresa)
                texto += formatear_caratula("Dirección", direccion_emb)
                texto += formatear_caratula("Ph", emb.telefono)
                texto += formatear_caratula("RUT", emb.ruc)
                texto += formatear_caratula("Contactos", emb.contactos)
            else:
                texto += "<b>Embarcador:</b> S/I<br><b>Datos del embarcador:</b><br>"
                texto += formatear_caratula("Empresa", "S/I")
                texto += formatear_caratula("Dirección", "S/I")
                texto += formatear_caratula("Ph", "S/I")
                texto += formatear_caratula("RUT", "S/I")
                texto += formatear_caratula("Contactos", "S/I")
            texto += '<br>'

            # Consignatario
            con = MantenimientosClientes.objects.filter(codigo=row.consignatario_codigo).first()
            if con:
                con_ciudad = MantenimientosCiudades.objects.filter(codedi=con.ciudad).first()
                direccion_con = f"{con.direccion} - {con_ciudad.nombre if con_ciudad else 'S/I'} - {con.pais}"
                texto += f"<b>Consignatario: {con.empresa}</b><br>"
                texto += "<b>Datos del consignatario:</b><br>"
                texto += formatear_caratula("Empresa", con.empresa)
                texto += formatear_caratula("Dirección", direccion_con)
                texto += formatear_caratula("Ph", con.telefono)
                texto += formatear_caratula("RUT", con.ruc)
                texto += formatear_caratula("Contactos", con.contactos)
            else:
                texto += "<b>Consignatario:</b> S/I<br><b>Datos del consignatario:</b><br>"
                texto += formatear_caratula("Empresa", "S/I")
                texto += formatear_caratula("Dirección", "S/I")
                texto += formatear_caratula("Ph", "S/I")
                texto += formatear_caratula("RUT", "S/I")
                texto += formatear_caratula("Contactos", "S/I")
            texto += '<br>'

            # Agente
            agente_ciudad = MantenimientosClientes.objects.filter(codigo=row.agente_codigo).first()

            if agente_ciudad:
                ciudad = MantenimientosCiudades.objects.filter(codedi=agente_ciudad.ciudad).first()
                agente_ciudad_nombre = ciudad.nombre if ciudad else "S/I"
            else:
                agente_ciudad_nombre = "S/I"

            texto += f"<b>Agente:</b> {row.agente or ''} - {agente_ciudad_nombre}<br>"
            texto += f"<b>Deposito:</b> {row.deposito or ''}<br><br>"
            texto += '<span style="display: block; border-top: 0.2pt solid #CCC; margin: 2px 0;"></span><br>'

            # Detalle del embarque
            texto += "<b>Detalle del embarque:</b><br>"
            movimiento = None
            if not aereo:
                envases = Envases.objects.filter(numero=id)
                for registro in envases:
                    peso = f"{registro.peso:.3f}" if registro.peso else "0.000"
                    volumen = f"{registro.volumen:.3f}" if registro.volumen else "0.000"

                    texto += (
                        f"{int(registro.cantidad or 0)}x{registro.unidad.upper() if registro.unidad else ''} {registro.movimiento if registro.movimiento else 'S/I'} "
                        f"{registro.tipo.upper() if registro.tipo else ''} "
                        f"CNTR: {registro.nrocontenedor or ''} SEAL: {registro.precinto or ''} "
                        f"WT: {peso} VOL: {volumen}<br>"
                    )
                    movimiento=registro.movimiento

            # Detalle de mercadería
            embarque = Cargaaerea.objects.filter(numero=id)
            for e in embarque:
                texto += formatear_caratula("Nro Bultos", f"{e.bultos} {e.tipo}") if movimiento is not None and movimiento == 'LCL/LCL' else formatear_caratula("Nro Bultos", f"{e.bultos}")
                texto += formatear_caratula("Mercadería", e.producto.nombre if e.producto else '')
                texto += '<br>'
                texto += formatear_caratula("Peso", e.bruto)
                texto += formatear_caratula("Volumen", e.cbm)
                texto += '<br><span style="display: block; border-top: 0.2pt solid #CCC; margin: 2px 0;"></span><br>'

            texto += formatear_caratula("Forma de pago", row.pago)
            texto += formatear_caratula("Vendedor", row.vendedor)
            texto += '</div>'

            resultado['resultado'] = 'exito'
            resultado['texto'] = texto
        except Exception as e:
            resultado['resultado'] = str(e)
    else:
        resultado['resultado'] = 'Ha ocurrido un error.'
    return HttpResponse(json.dumps(resultado), "application/json")




