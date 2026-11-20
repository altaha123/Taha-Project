import Capacitor
import UIKit
import WebKit

/// The app's one screen: Capacitor's web view, plus the plugin below.
/// SceneDelegate creates this instead of a plain CAPBridgeViewController.
class ShellViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        super.capacitorDidLoad()
        bridge?.registerPluginInstance(ShellPlugin())
    }
}

/// The two things the pages need from the phone that no published plugin
/// gives them. Called from mobile/src/bridge.js as "AltahaShell". The Android
/// half is android/app/src/main/java/in/altahascreener/app/ShellPlugin.java.
///
/// print          window.print() does nothing in a web view. This opens the
///                system print sheet, which is also how a page is saved as a
///                PDF. With no html it prints the page on screen; with html
///                it prints that document instead (the portfolio report,
///                which the site writes into a new window).
///
/// setBackground  The colour behind the page. A page is blank for a moment
///                while it loads, and that moment is this colour, so a dark
///                page does not flash white on every tap.
@objc(ShellPlugin)
public class ShellPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShellPlugin"
    public let jsName = "AltahaShell"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "print", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setBackground", returnType: CAPPluginReturnPromise)
    ]

    @objc func print(_ call: CAPPluginCall) {
        let name = call.getString("name") ?? "Altaha Screener"
        let html = call.getString("html") ?? ""

        DispatchQueue.main.async {
            let controller = UIPrintInteractionController.shared
            let info = UIPrintInfo(dictionary: nil)
            info.jobName = name
            info.outputType = .general
            controller.printInfo = info

            if !html.isEmpty {
                controller.printFormatter = UIMarkupTextPrintFormatter(markupText: html)
            } else if let webView = self.bridge?.webView {
                controller.printFormatter = webView.viewPrintFormatter()
            } else {
                call.reject("There is no page to print.")
                return
            }

            // Resolves when the sheet closes, printed or not: the page is
            // waiting on this to put itself back the way it was.
            controller.present(animated: true) { _, _, _ in
                call.resolve()
            }
        }
    }

    @objc func setBackground(_ call: CAPPluginCall) {
        guard let color = ShellPlugin.color(hex: call.getString("color") ?? "") else {
            call.reject("Not a colour.")
            return
        }
        DispatchQueue.main.async {
            if let webView = self.bridge?.webView {
                webView.backgroundColor = color
                webView.scrollView.backgroundColor = color
            }
            self.bridge?.viewController?.view.backgroundColor = color
            call.resolve()
        }
    }

    /// "#RRGGBB" to a colour. Nothing else is ever sent.
    static func color(hex: String) -> UIColor? {
        let digits = hex.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "#", with: "")
        guard digits.count == 6, let value = UInt32(digits, radix: 16) else { return nil }
        return UIColor(
            red: CGFloat((value >> 16) & 0xFF) / 255.0,
            green: CGFloat((value >> 8) & 0xFF) / 255.0,
            blue: CGFloat(value & 0xFF) / 255.0,
            alpha: 1.0)
    }
}
