// Prints, for each MIME type given, whether Qt knows it and which applications
// KService offers for it (what Dolphin's "Open With" menu lists).
// Exit code 1 if a type is unknown or has no application.
#include <KApplicationTrader>
#include <QCoreApplication>
#include <QMimeDatabase>
#include <QTextStream>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);
    int status = 0;
    const QStringList types = app.arguments().mid(1);
    for (const QString &type : types) {
        const QMimeType mime = QMimeDatabase().mimeTypeForName(type);
        QStringList names;
        for (const KService::Ptr &service : KApplicationTrader::queryByMimeType(type)) {
            names << service->name();
        }
        out << type << ": " << (mime.isValid() ? "known" : "UNKNOWN") << "; apps: "
            << (names.isEmpty() ? QStringLiteral("NONE") : names.join(QStringLiteral(", "))) << '\n';
        if (!mime.isValid() || names.isEmpty()) {
            status = 1;
        }
    }
    return status;
}
