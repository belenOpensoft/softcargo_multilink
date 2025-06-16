import datetime
import io
from collections import defaultdict
from decimal import Decimal

import xlsxwriter
from MySQLdb.constants.FIELD_TYPE import DATETIME
from django.http import HttpResponse
from django.shortcuts import render

from administracion_contabilidad.models import Movims
from consultas_administrativas.forms import ReporteMovimientosForm, BalanceCuentasCobrarForm
from consultas_administrativas.models import VReporteSubdiarioVentas, VCuentasCobrarBalance
from mantenimientos.models import Clientes

TIPOS = {
    'FC':20,
    'FP':40,
    'NC':21,
    'NP':41,
    'RP':45,
    'RC':25,
    'BO':24
}

def balance_cobrar_old(request):
    if request.method == 'POST':
        form = BalanceCuentasCobrarForm(request.POST)
        if form.is_valid():
            fecha_hasta = form.cleaned_data['fecha_hasta']
            moneda = form.cleaned_data['moneda']
            consolidar_dolares = form.cleaned_data['consolidar_dolares']
            consolidar_moneda_nac = form.cleaned_data['consolidar_moneda_nac']


            if moneda and not consolidar_moneda_nac and not consolidar_dolares:
                queryset = VCuentasCobrarBalance.objects.filter(fecha__lte=fecha_hasta,moneda=moneda.codigo)
            else:
                queryset = VCuentasCobrarBalance.objects.filter(fecha__lte=fecha_hasta)

            # Generar Excel
            return generar_excel_balance_cobrar(queryset, fecha_hasta,moneda,consolidar_dolares,consolidar_moneda_nac)

    else:
        form = BalanceCuentasCobrarForm()

    return render(request, 'ventas_ca/balance_cobrar.html', {'form': form})

def balance_cobrar_v2(request):
    if request.method == 'POST':
        form = BalanceCuentasCobrarForm(request.POST)
        if form.is_valid():
            fecha_hasta = form.cleaned_data['fecha_hasta']
            moneda = form.cleaned_data['moneda']
            consolidar_dolares = form.cleaned_data['consolidar_dolares']
            consolidar_moneda_nac = form.cleaned_data['consolidar_moneda_nac']

            nombres = {}
            saldos = defaultdict(Decimal)
            clientes = Clientes.objects.all().order_by('empresa')
            for cli in clientes:
                #movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gte='2015-03-17',mcliente=cli.codigo).order_by('mfechamov','id')
                if isinstance(cli.fechadenegado,datetime.datetime):
                    movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gte=cli.fechadenegado, mcliente=cli.codigo).order_by('mfechamov','id')
                else:
                    movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mcliente=cli.codigo).order_by('mfechamov','id')

                saldo=0
                if movimientos.count() > 0:
                    #print( cli.empresa,': ',movimientos.count())
                    for m in movimientos:
                        cliente = cli.codigo
                        nombres[cliente] = cli.empresa
                        if m.mtipo == TIPOS['FC']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['FP']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['NC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['RP']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['RC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['BO']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo not in TIPOS.values():
                            print(f"No contabilizado: tipo={m.mtipo}, monto={m.mtotal}, cliente={cliente}")
                        print('saldo: ', saldos[cliente])
                        print('movimiento: ',m.mfechamov,' ', m.mtipo, 'monto: ',m.mtotal)

            for cliente, saldo in saldos.items():
                if saldo !=0:
                    print(f'Cliente: {nombres[cliente]} (#{cliente}) - Saldo final: {saldo:.2f}')

                # Generar Excel
               # return generar_excel_balance_cobrar(queryset, fecha_hasta,moneda,consolidar_dolares,consolidar_moneda_nac)

    else:
        form = BalanceCuentasCobrarForm()

    return render(request, 'ventas_ca/balance_cobrar.html', {'form': form})

def balance_cobrar_v3(request):
    if request.method == 'POST':
        form = BalanceCuentasCobrarForm(request.POST)
        if form.is_valid():
            fecha_hasta = form.cleaned_data['fecha_hasta']
            moneda = form.cleaned_data['moneda']
            consolidar_dolares = form.cleaned_data['consolidar_dolares']
            consolidar_moneda_nac = form.cleaned_data['consolidar_moneda_nac']

            nombres = {}
            saldos = defaultdict(Decimal)
            clientes = Clientes.objects.all().order_by('empresa')
            clientes= clientes.filter(codigo=2052)
            for cli in clientes:
                #movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gte='2015-03-17',mcliente=cli.codigo).order_by('mfechamov','id')
                if isinstance(cli.fechadenegado,datetime.datetime):
                    movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gt=cli.fechadenegado, mcliente=cli.codigo,mactivo='S').order_by('mfechamov','id')
                else:
                    movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mcliente=cli.codigo,mactivo='S').order_by('mfechamov','id')

                aux = movimientos.count()
                saldo=0
                if movimientos.count() > 0:
                    #print( cli.empresa,': ',movimientos.count())
                    for m in movimientos:
                        cliente = cli.codigo
                        nombres[cliente] = cli.empresa
                        if m.mtipo == TIPOS['FC']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['FP']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['NC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['RP']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['RC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['BO']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo not in TIPOS.values():
                            pass
                            #print(f"No contabilizado: tipo={m.mtipo}, monto={m.mtotal}, cliente={cliente}")
                        print('movimiento: ',m.mfechamov,' ', m.mtipo, 'monto: ',m.mtotal)
                        print('saldo: ', saldos[cliente])

                        #print(cli.empresa)

            for cliente, saldo in saldos.items():
                if saldo !=0:
                    print(f'Cliente: {nombres[cliente]} (#{cliente}) - Saldo final: {saldo:.2f}')

                # Generar Excel
               # return generar_excel_balance_cobrar(queryset, fecha_hasta,moneda,consolidar_dolares,consolidar_moneda_nac)

    else:
        form = BalanceCuentasCobrarForm()

    return render(request, 'ventas_ca/balance_cobrar.html', {'form': form})

def balance_cobrar_ajuste(request):
    if request.method == 'POST':
        form = BalanceCuentasCobrarForm(request.POST)
        if form.is_valid():
            fecha_hasta = form.cleaned_data['fecha_hasta']
            moneda = form.cleaned_data['moneda']
            consolidar_dolares = form.cleaned_data['consolidar_dolares']
            consolidar_moneda_nac = form.cleaned_data['consolidar_moneda_nac']

            nombres = {}
            saldos = defaultdict(Decimal)
            clientes = Clientes.objects.all().order_by('empresa')
            #clientes= clientes.filter(codigo=2052)
            for cli in clientes:
                cliente = cli.codigo
                nombres[cliente] = cli.empresa
                #movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gte='2015-03-17',mcliente=cli.codigo).order_by('mfechamov','id')
                if isinstance(cli.fechadenegado,datetime.datetime):
                    movimientos = Movims.objects.only('mfechamov', 'mtipo', 'mtotal').filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gt=cli.fechadenegado, mcliente=cli.codigo,mactivo='S',mtipo__in=TIPOS.values()).order_by('mfechamov','id')
                else:
                    movimientos = Movims.objects.only('mfechamov', 'mtipo', 'mtotal').filter(mmoneda=2,mfechamov__lte=fecha_hasta,mcliente=cli.codigo,mactivo='S',mtipo__in=TIPOS.values()).order_by('mfechamov','id')

                aux = movimientos.count()
                saldo=0
                if movimientos.count() > 0:
                    #print( cli.empresa,': ',movimientos.count())
                    for m in movimientos:

                        if m.mtipo == TIPOS['FC']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['FP']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['NC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['RP']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['RC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['BO']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo not in TIPOS.values():
                            pass
                            #print(f"No contabilizado: tipo={m.mtipo}, monto={m.mtotal}, cliente={cliente}")
                        #print('movimiento: ',m.mfechamov,' ', m.mtipo, 'monto: ',m.mtotal)
                        #print('saldo: ', saldos[cliente])


                # 🔹 Agregar ajustes sin importar la fecha
                ajustes = Movims.objects.only('mfechamov', 'mtipo', 'mtotal').filter(
                    mcliente=cli.codigo,
                    mnombremov='AJUSTE',
                    mactivo='S',
                    mmoneda=2,
                    mtipo__in=(25,45)
                )
                for a in ajustes:
                    if a.mtipo==45: #si el ajuste es hacia factura prov
                        saldos[cli.codigo] += a.mtotal
                    elif a.mtipo == 25: # si el ajuste es hacia factura de ocean
                        saldos[cli.codigo] -= a.mtotal
                    else:
                        continue
                    #print('ajuste: ', a.mfechamov, 'monto:', a.mtotal, 'tipo: ',a.mtipo)
                    #print('saldo (con ajuste):', saldos[cli.codigo])

                print(cli.empresa)

            for cliente, saldo in saldos.items():
                if saldo != 0:
                    print(f'Cliente: {nombres[cliente]} (#{cliente}) - Saldo final: {saldo:.2f}')

                # Generar Excel
               # return generar_excel_balance_cobrar(queryset, fecha_hasta,moneda,consolidar_dolares,consolidar_moneda_nac)

    else:
        form = BalanceCuentasCobrarForm()

    return render(request, 'ventas_ca/balance_cobrar.html', {'form': form})

def balance_cobrar(request):
    if request.method == 'POST':
        form = BalanceCuentasCobrarForm(request.POST)
        if form.is_valid():
            fecha_hasta = form.cleaned_data['fecha_hasta']
            moneda = form.cleaned_data['moneda']
            consolidar_dolares = form.cleaned_data['consolidar_dolares']
            consolidar_moneda_nac = form.cleaned_data['consolidar_moneda_nac']

            nombres = {}
            socios = {}
            saldos = defaultdict(Decimal)

            clientes = Clientes.objects.only('codigo', 'empresa', 'fechadenegado','socio').order_by('empresa')
            #clientes= clientes.filter(codigo=3900)
            for cli in clientes:
                cliente = cli.codigo
                nombres[cliente] = cli.empresa
                socios[cliente] = cli.socio
                #movimientos = Movims.objects.filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gte='2015-03-17',mcliente=cli.codigo).order_by('mfechamov','id')
                if isinstance(cli.fechadenegado,datetime.datetime):
                    movimientos = Movims.objects.only('mfechamov', 'mtipo', 'mtotal').filter(mmoneda=2,mfechamov__lte=fecha_hasta,mfechamov__gt=cli.fechadenegado, mcliente=cli.codigo,mactivo='S').order_by('mfechamov','id')
                else:
                    movimientos = Movims.objects.only('mfechamov', 'mtipo', 'mtotal').filter(mmoneda=2,mfechamov__lte=fecha_hasta,mcliente=cli.codigo,mactivo='S').order_by('mfechamov','id')

                saldo=0
                if movimientos.exists():
                    #print( cli.empresa,': ',movimientos.count())
                    for m in movimientos:
                        cliente = cli.codigo
                        nombres[cliente] = cli.empresa
                        if m.mtipo == TIPOS['FC']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo == TIPOS['NC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['RC']:
                            saldos[cliente] -= m.mtotal
                        elif m.mtipo == TIPOS['BO']:
                            saldos[cliente] += m.mtotal
                        elif m.mtipo not in TIPOS.values():
                            pass
                            #print(f"No contabilizado: tipo={m.mtipo}, monto={m.mtotal}, cliente={cliente}")
                        #print('movimiento: ',m.mfechamov,' ', m.mtipo, 'monto: ',m.mtotal)
                        #print('saldo: ', saldos[cliente])

                        print(cli.empresa)

            for cliente, saldo in saldos.items():
                if saldo !=0:
                    print(f'Cliente: {nombres[cliente]} (#{cliente}) - Socio: {socios[cliente]} - Saldo final: {saldo:.2f}')

                # Generar Excel
               # return generar_excel_balance_cobrar(queryset, fecha_hasta,moneda,consolidar_dolares,consolidar_moneda_nac)

    else:
        form = BalanceCuentasCobrarForm()

    return render(request, 'ventas_ca/balance_cobrar.html', {'form': form})

def generar_excel_balance_cobrar(queryset, fecha_hasta, moneda, consolidar_dolares=False, consolidar_moneda_nac=False):
    try:
        if consolidar_dolares:
            nombre_moneda = "DOLARES USA"
            moneda_destino = 2
        elif consolidar_moneda_nac:
            nombre_moneda = "MONEDA NACIONAL"
            moneda_destino = 1
        else:
            nombre_moneda = moneda.nombre.upper() if moneda else "TODAS LAS MONEDAS"
            moneda_destino = None

        fecha_formateada = fecha_hasta.strftime('%d/%m/%Y')
        titulo = f'Cuentas a cobrar al {fecha_formateada} - {nombre_moneda}'
        nombre_archivo = f'Balance_Cuentas_Cobrar_{fecha_hasta}.xlsx'

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Balance")

        # Formatos
        header_format = workbook.add_format({'bold': True, 'bg_color': '#d9d9d9', 'border': 1, 'align': 'center'})
        title_format = workbook.add_format({'bold': True, 'font_size': 12})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        total_format = workbook.add_format({'bold': True, 'num_format': '#,##0.00', 'top': 2, 'border': 1})
        total_label_format = workbook.add_format({'bold': True, 'top': 2, 'border': 1})
        text_format = workbook.add_format({'border': 1})

        # Título
        worksheet.merge_range('A1:C1', titulo, title_format)

        # Encabezados
        encabezados = ['Código', 'Nombre', 'Saldo']
        for col_num, encabezado in enumerate(encabezados):
            worksheet.write(1, col_num, encabezado, header_format)

        row = 2
        total_general = Decimal('0.00')

        for obj in queryset:
            saldo = Decimal(obj.saldo or 0)
            moneda_origen = obj.moneda

            # Valores de arbitraje y paridad si están disponibles en el modelo
            arbitraje = getattr(obj, 'arbitraje', Decimal('1'))
            paridad = getattr(obj, 'paridad', Decimal('1'))

            if moneda_destino and moneda_origen != moneda_destino:
                saldo = convertir_monto(saldo, moneda_origen, moneda_destino, arbitraje, paridad)

            worksheet.write(row, 0, obj.codigo, text_format)
            worksheet.write(row, 1, obj.nombre, text_format)
            worksheet.write(row, 2, float(saldo), money_format)

            total_general += saldo
            row += 1

        # Escribir el total al final
        worksheet.write(row, 1, 'TOTAL GENERAL', total_label_format)
        worksheet.write(row, 2, float(total_general), total_format)

        # Ajuste de ancho
        worksheet.set_column('A:A', 10)  # Código
        worksheet.set_column('B:B', 40)  # Nombre
        worksheet.set_column('C:C', 18)  # Saldo

        workbook.close()
        output.seek(0)

        response = HttpResponse(
            output.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
        return response

    except Exception as e:
        raise RuntimeError(f"Error al generar el Excel de balance: {e}")


def convertir_monto(monto, origen, destino, arbitraje, paridad):
    """
    Convierte un monto desde 'origen' a 'destino' utilizando arbitraje y paridad.
    origen y destino son enteros representando códigos de moneda:
    1 = moneda nacional, 2 = dólar, otros = otras monedas (ej: euro)
    """

    try:
        if origen == destino or monto == 0:
            return round(monto, 2)

        if destino == 1:  # convertir a moneda nacional
            if origen == 2 and arbitraje:
                return round(monto * arbitraje, 2)
            elif origen not in [1, 2] and arbitraje and paridad:
                dolares = monto / paridad
                return round(dolares * arbitraje, 2)

        elif destino == 2:  # convertir a dólares
            if origen == 1 and arbitraje:
                return round(monto / arbitraje, 2)
            elif origen not in [1, 2] and paridad:
                return round(monto / paridad, 2)

        else:  # convertir a otra moneda
            if origen == 1 and arbitraje and paridad:
                dolares = monto / arbitraje
                return round(dolares * paridad, 2)
            elif origen == 2 and paridad:
                return round(monto * paridad, 2)
            elif origen == destino:
                return round(monto, 2)

        # Si no se puede convertir, devolver sin modificar
        return round(monto, 2)
    except Exception as e:
        return str(e)