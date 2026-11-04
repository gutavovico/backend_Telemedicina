"""Optional end-to-end verification against scripts.cu34_local and Angular dev server.
Requires `pip install playwright` and local Microsoft Edge. No API mocking.
"""
import re
import os
from getpass import getpass
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect


def run():
    password = os.environ.get('CU34_LOCAL_PASSWORD') or getpass('Contraseña del superadministrador local para la prueba web: ')
    code = 'WEB_' + uuid4().hex[:10].upper()
    screenshots = Path(__file__).resolve().parents[1] / 'tmp'
    screenshots.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://localhost:4200/admin/planes')
        page.locator('[formcontrolname="email"]').fill('cu34-local@example.com')
        page.locator('[formcontrolname="password"]').fill(password)
        page.get_by_role('button', name=re.compile('Iniciar sesi',re.I)).click()
        expect(page.get_by_role('heading', name='Catálogo de planes de suscripción')).to_be_visible()
        expect(page.get_by_role('link',name='Planes',exact=True)).to_be_visible()
        page.get_by_role('button',name='Nuevo plan',exact=False).click()
        page.get_by_label('Código del plan',exact=True).fill(code)
        page.get_by_label('Nombre del plan',exact=True).fill('Plan de prueba web')
        page.get_by_label('Descripción',exact=False).fill('Condiciones únicamente para prueba aislada')
        page.get_by_label('Precio mensual (Bs)',exact=True).fill('123.45')
        page.get_by_label('Límite de Médicos',exact=True).fill('3')
        page.get_by_label('Límite de Sedes',exact=True).fill('0')
        page.locator('.resource').filter(has=page.get_by_role('heading',name='Consultas por ciclo mensual',exact=True)).get_by_label('Sin límite',exact=True).check()
        page.get_by_label('Laboratorio',exact=True).check()
        page.get_by_label('Días de demora permitida',exact=True).fill('0')
        with page.expect_response(lambda r: r.url.endswith('/api/v1/planes') and r.request.method=='POST') as created:
            page.get_by_role('button',name='Crear plan',exact=True).click()
        assert created.value.status==201, created.value.text()
        plan = created.value.json()
        expect(page.get_by_text('Plan guardado correctamente.',exact=True)).to_be_visible()
        assert plan['version']['limite_consultas'] is None
        assert plan['version']['precio_mensual']=='123.45'
        page.get_by_role('button',name='Editar condiciones',exact=True).click()
        page.get_by_label('Precio mensual (Bs)',exact=True).fill('199.90')
        with page.expect_response(lambda r: r.url.endswith(f"/{plan['id']}/versiones") and r.request.method=='POST') as updated:
            page.get_by_role('button',name='Guardar nueva versión',exact=True).click()
        assert updated.value.status==201
        assert updated.value.json()['version_actual']==2
        page.get_by_role('button',name='Ver historial de versiones',exact=True).click()
        page.get_by_role('button',name='Versión 1 · Plan de prueba web',exact=True).click()
        expect(page.get_by_label('Precio mensual (Bs)',exact=True)).to_have_value('123.45')
        expect(page.get_by_label('Precio mensual (Bs)',exact=True)).to_be_disabled()
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(screenshots/'cu34-desktop.png'),full_page=True,animations='disabled')
        # Confirm cancel leaves the plan active, then commit the explicit confirmation.
        page.get_by_label('Buscar plan',exact=True).fill(code)
        page.get_by_role('button',name='Buscar',exact=True).click()
        row=page.get_by_role('row').filter(has_text=code)
        expect(row).to_have_count(1)
        row.get_by_role('button',name='Desactivar',exact=True).click()
        dialog=page.get_by_role('alertdialog')
        dialog.get_by_role('button',name='Cancelar',exact=True).click()
        expect(row.get_by_text('Activo',exact=True)).to_be_visible()
        row.get_by_role('button',name='Desactivar',exact=True).click()
        with page.expect_response(lambda r: r.url.endswith(f"/{plan['id']}/estado") and r.request.method=='PATCH') as deactivated:
            dialog.get_by_role('button',name='Confirmar desactivación',exact=True).click()
        assert deactivated.value.status==200
        expect(row.get_by_text('Desactivado',exact=True)).to_be_visible()
        expect(row.get_by_role('button',name='Editar',exact=True)).to_have_count(0)
        # Reload verifies database persistence, not component state alone.
        page.reload()
        expect(page.get_by_role('heading',name='Catálogo de planes de suscripción')).to_be_visible()
        page.get_by_label('Buscar plan',exact=True).fill(code)
        page.get_by_role('button',name='Buscar',exact=True).click()
        expect(page.get_by_role('row').filter(has_text=code).get_by_text('Desactivado',exact=True)).to_be_visible()
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("document.querySelector('app-admin-layout aside').getBoundingClientRect().right <= 1")
        page.get_by_role('row').filter(has_text=code).get_by_role('button',name='Ver',exact=True).click()
        expect(page.get_by_role('heading',name='Detalle del plan',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Page overflows mobile viewport'
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(screenshots/'cu34-mobile.png'),full_page=True,animations='disabled')
        assert not errors, errors
        browser.close()
    print('PASS: login real, creación, edición, historial inmutable, cancelar/confirmar desactivación, persistencia y móvil.')


if __name__=='__main__': run()
