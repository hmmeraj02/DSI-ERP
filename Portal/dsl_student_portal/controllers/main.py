from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home
import werkzeug
import logging

_logger = logging.getLogger(__name__)


class DSLLoginController(Home):

    @http.route("/web/login", type="http", auth="public", website=True, sitemap=False)
    def web_login(self, redirect=None, **kw):
        self.ensure_db()

        if request.session.uid:
            return request.redirect(
                self._login_redirect(request.session.uid, redirect=redirect)
            )

        if request.httprequest.method == "POST":
            old_uid = request.session.uid
            login_type = request.params.get("type")

            try:
                super(DSLLoginController, self).web_login(redirect=redirect, **kw)
            except Exception as e:
                _logger.error(f"Login error: {e}")

            if request.session.uid and request.session.uid != old_uid:
                user = request.env["res.users"].sudo().browse(request.session.uid)

                if (
                    user.id == request.env.ref("base.user_admin").id
                    or user.login == "admin"
                ):
                    _logger.info(f"Admin user logged in: {user.login}")
                    return request.redirect(
                        self._login_redirect(request.session.uid, redirect=redirect)
                    )

                partner = user.partner_id
                identity_type = (
                    partner.identity_type if hasattr(partner, "identity_type") else None
                )

                if login_type == "student" and identity_type != "student":
                    request.session.logout(keep_db=True)
                    values = self._prepare_login_values(request.params)
                    values["error"] = (
                        "Access Denied: This login is for students only. Please use the correct login portal."
                    )
                    response = request.render("web.login", values)
                    response.headers["X-Frame-Options"] = "SAMEORIGIN"
                    return response

                elif login_type == "agent" and identity_type != "agent":
                    request.session.logout(keep_db=True)
                    values = self._prepare_login_values(request.params)
                    values["error"] = (
                        "Access Denied: This login is for agents only. Please use the correct login portal."
                    )
                    response = request.render("web.login", values)
                    response.headers["X-Frame-Options"] = "SAMEORIGIN"
                    return response

                _logger.info(f"User {user.login} logged in as {identity_type}")
                return request.redirect("/my/home")

            values = self._prepare_login_values(request.params)
            if "error" not in values and request.params.get("login"):
                values["error"] = "Wrong login/password"

            response = request.render("web.login", values)
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            return response

        values = self._prepare_login_values(request.params)
        response = request.render("web.login", values)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    def _prepare_login_values(self, params):
        """Prepare values for login page"""
        values = {
            "databases": None,
            "error": params.get("error"),
            "message": params.get("message"),
            "login": params.get("login", ""),
            "redirect": params.get("redirect"),
        }

        try:
            signup_config = self.get_auth_signup_config()
            if signup_config:
                values.update(signup_config)
        except:
            pass

        if params:
            values.update(params)

        return values

    def _login_redirect(self, uid, redirect=None):
        if redirect:
            return redirect

        user = request.env["res.users"].sudo().browse(uid)

        if user.id == request.env.ref("base.user_admin").id or user.login == "admin":
            return "/web"

        return "/my/home"

    def ensure_db(self):
        db = request.session.db
        if not db and request.httprequest.method == "GET":
            raise werkzeug.exceptions.Redirect("/web/database/selector", 303)
