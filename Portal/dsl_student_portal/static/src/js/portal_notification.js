/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

export class PortalNotification extends Component {
    setup() {
        this.busService = useService("bus_service");
        this.notification = useService("notification");

        onWillStart(async () => {
            this.busService.addChannel("dsl_student_portal_notices");
            this.busService.subscribe("dsl_student_portal_notices", (notifications) => {
                this._onNotification(notifications);
            });
        });
    }

    _onNotification(notifications) {

        const notes = Array.isArray(notifications) ? notifications : [notifications];

        for (const note of notes) {

            const payload = note.payload || note;
            const type = payload.type || note.type;

            if (type === "notice_published") {
                this.notification.add(payload.title || "New Notice", {
                    title: "New Notice Published",
                    type: "info",
                });

                // Update badge
                // Since this component might be mounted on the badge itself (if selector matches), 
                // 'this.el' would be the badge element.
                // However, if we simply want to manipulate the DOM or if selector matches a wrapper.
                // Given "selector: #navbar_notification_badge", the component IS the badge representation?
                // Actually, public components are mounted *inside* the selector element usually, or replace it?
                // Documentation says: "The component will be mounted in the element matching the selector."

                // Update badge
                const badge = document.querySelector("#navbar_notification_badge");
                if (badge) {
                    let currentCount = parseInt(badge.innerText.trim()) || 0;
                    // If badge was hidden (likely 0), show it now
                    if (badge.classList.contains('d-none')) {
                        currentCount = 0;
                        badge.classList.remove("d-none");
                    }
                    badge.innerText = currentCount + 1;

                    // Add animation class if available or simple CSS transition
                    // badge.classList.add("animate__animated", "animate__bounceIn");
                }
            }
        }
    }
}
PortalNotification.template = "dsl_student_portal.PortalNotification";


registry.category("public_components").add("dsl_student_portal.PortalNotification", {
    Component: PortalNotification,
    selector: "#navbar_notification_badge", // Target the navbar badge
});
