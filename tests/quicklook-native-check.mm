#include "quicklook_macos.h"

#include <QApplication>
#include <QFile>
#include <QKeyEvent>
#include <QPointer>
#include <QTemporaryDir>
#include <QTimer>
#include <QUrl>
#include <QWidget>

#import <AppKit/AppKit.h>
#import <QuickLookUI/QuickLookUI.h>

#include <iostream>

class KeyWindow : public QWidget
{
public:
    QList<int> keys;

protected:
    void keyPressEvent(QKeyEvent *event) override
    {
        keys.append(event->key());
    }
};

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QTemporaryDir directory;
    if (!directory.isValid()) {
        std::cerr << "Could not create temporary test files\n";
        return 1;
    }
    const QString filename = directory.filePath(QStringLiteral("preview.txt"));
    QFile file(filename);
    if (!file.open(QIODevice::WriteOnly) || file.write("Quick Look test\n") < 0) {
        std::cerr << "Could not write temporary test file\n";
        return 1;
    }
    file.close();

    KeyWindow window;
    window.setFocusPolicy(Qt::StrongFocus);
    QWidget otherWindow;
    window.setWindowTitle(QStringLiteral("Dolphin Quick Look Test"));
    window.resize(320, 200);
    window.show();
    window.raise();
    window.activateWindow();
    [NSApp activateIgnoringOtherApps:YES];

    QTimer activationPoll;
    activationPoll.setInterval(200);
    QObject::connect(&activationPoll, &QTimer::timeout, &app, [&] {
        NSView *view = (__bridge NSView *)reinterpret_cast<void *>(window.winId());
        NSWindow *nativeWindow = view.window;
        if (!NSApp.active || !nativeWindow) {
            return;
        }
        activationPoll.stop();
        NSResponder *previous = nativeWindow.nextResponder;
        const QUrl url = QUrl::fromLocalFile(filename);
        DolphinQuickLook::show({url}, &window);
        QTimer::singleShot(700, &app, [&, nativeWindow, previous] {
            QLPreviewPanel *panel = [QLPreviewPanel sharedPreviewPanel];
            id controller = panel.currentController;
            if (!DolphinQuickLook::isVisible(&window) || !controller || panel.dataSource != controller
                || ![controller isKindOfClass:NSClassFromString(@"DolphinQuickLookSource")]) {
                std::cerr << "Quick Look did not acquire the expected controller and data source\n";
                DolphinQuickLook::close(&window);
                app.exit(1);
                return;
            }
            if (panel.delegate != controller) {
                std::cerr << "Quick Look did not install its event delegate\n";
                app.exit(1);
                return;
            }
            const unsigned short keyCodes[] = {123, 124, 125, 126};
            const unichar characters[] = {NSLeftArrowFunctionKey, NSRightArrowFunctionKey, NSDownArrowFunctionKey, NSUpArrowFunctionKey};
            for (int i = 0; i < 4; ++i) {
                NSString *character = [NSString stringWithCharacters:&characters[i] length:1];
                NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0
                    timestamp:0 windowNumber:panel.windowNumber context:nil characters:character
                    charactersIgnoringModifiers:character isARepeat:NO keyCode:keyCodes[i]];
                [panel sendEvent:key];
            }
            if (window.keys != QList<int>({Qt::Key_Left, Qt::Key_Right, Qt::Key_Down, Qt::Key_Up})) {
                std::cerr << "The Qt window did not receive all four arrow keys: " << window.keys.size() << "\n";
                app.exit(1);
                return;
            }
            if ([panel.dataSource numberOfPreviewItemsInPreviewPanel:panel] != 1) {
                std::cerr << "Quick Look did not receive the test item\n";
                DolphinQuickLook::close(&window);
                app.exit(1);
                return;
            }
            otherWindow.setWindowTitle(QStringLiteral("Dolphin Quick Look Second Window"));
            otherWindow.resize(320, 200);
            otherWindow.show();
            otherWindow.raise();
            otherWindow.activateWindow();
            QPointer<QTimer> secondActivationPoll = new QTimer(&app);
            secondActivationPoll->setInterval(100);
            QObject::connect(secondActivationPoll, &QTimer::timeout, &app, [&, nativeWindow, previous, secondActivationPoll] {
                if (!otherWindow.isActiveWindow()) {
                    return;
                }
                secondActivationPoll->stop();
                secondActivationPoll->deleteLater();
                NSView *secondView = (__bridge NSView *)reinterpret_cast<void *>(otherWindow.winId());
                NSWindow *secondNative = secondView.window;
                NSResponder *secondPrevious = secondNative.nextResponder;
                DolphinQuickLook::show({QUrl::fromLocalFile(filename)}, &otherWindow);
                QTimer::singleShot(700, &app, [&, nativeWindow, previous, secondNative, secondPrevious] {
                    QLPreviewPanel *secondPanel = [QLPreviewPanel sharedPreviewPanel];
                    id secondController = secondPanel.currentController;
                    if (!DolphinQuickLook::isVisible(&otherWindow) || !secondController
                        || secondPanel.dataSource != secondController || secondPanel.delegate != secondController) {
                        std::cerr << "The second window did not acquire Quick Look: visible="
                                  << DolphinQuickLook::isVisible(&otherWindow) << " controller=" << (secondController != nil)
                                  << " dataSource=" << (secondPanel.dataSource != nil)
                                  << " equal=" << (secondPanel.dataSource == secondController) << '\n';
                        DolphinQuickLook::close(&otherWindow);
                        app.exit(1);
                        return;
                    }
                    DolphinQuickLook::close(&window);
                    if (!DolphinQuickLook::isVisible(&otherWindow) || nativeWindow.nextResponder != previous) {
                        std::cerr << "Closing another window changed the active preview\n";
                        DolphinQuickLook::close(&otherWindow);
                        app.exit(1);
                        return;
                    }
                    DolphinQuickLook::close(&otherWindow);
                    DolphinQuickLook::show({QUrl::fromLocalFile(filename)}, &otherWindow);
                    QTimer::singleShot(1500, &app, [&, secondNative, secondPrevious] {
                        QLPreviewPanel *reopened = [QLPreviewPanel sharedPreviewPanel];
                        id reopenedController = reopened.currentController;
                        if (!NSApp.active) {
                            std::cerr << "The application lost focus; reopening was not tested\n";
                            app.exit(77);
                            return;
                        }
                        if (!DolphinQuickLook::isVisible(&otherWindow) || !reopenedController
                            || reopened.dataSource != reopenedController) {
                            std::cerr << "Quick Look did not reopen after a quick close: visible="
                                      << DolphinQuickLook::isVisible(&otherWindow) << " controller=" << (reopenedController != nil)
                                      << " dataSource=" << (reopened.dataSource != nil)
                                      << " active=" << otherWindow.isActiveWindow() << " app=" << NSApp.active << '\n';
                            DolphinQuickLook::close(&otherWindow);
                            app.exit(1);
                            return;
                        }
                        DolphinQuickLook::close(&otherWindow);
                        DolphinQuickLook::show({QUrl::fromLocalFile(filename)}, &otherWindow);
                        if (!DolphinQuickLook::isVisible(&otherWindow)) {
                            std::cerr << "A pending reopen was not marked as active\n";
                            app.exit(1);
                            return;
                        }
                        DolphinQuickLook::close(&otherWindow);
                        QTimer::singleShot(700, &app, [&, secondNative, secondPrevious, reopenedController] {
                            QLPreviewPanel *closed = [QLPreviewPanel sharedPreviewPanel];
                            if (DolphinQuickLook::isVisible(&otherWindow) || secondNative.nextResponder != secondPrevious
                                || closed.dataSource == reopenedController || closed.delegate == reopenedController) {
                                std::cerr << "The second window did not cancel reopening or release Quick Look: visible="
                                          << DolphinQuickLook::isVisible(&otherWindow) << " chain="
                                          << (secondNative.nextResponder == secondPrevious) << " controller="
                                          << (closed.currentController == reopenedController) << " dataSource="
                                          << (closed.dataSource == reopenedController) << " delegate="
                                          << (closed.delegate == reopenedController) << '\n';
                                app.exit(1);
                                return;
                            }
                            std::cout << "Quick Look native controller lifecycle and ownership: OK\n";
                            app.exit(0);
                        });
                    });
                });
            });
            secondActivationPoll->start();
            QTimer::singleShot(8000, &app, [&, secondActivationPoll] {
                if (secondActivationPoll && secondActivationPoll->isActive()) {
                    secondActivationPoll->stop();
                    std::cerr << "The second window did not become active; ownership was not tested\n";
                    app.exit(77);
                }
            });
        });
    });
    activationPoll.start();
    QTimer::singleShot(12000, &app, [&] {
        if (activationPoll.isActive()) {
            std::cerr << "The test window did not become active; controller acquisition was not tested\n";
            app.exit(77);
        }
    });
    return app.exec();
}
