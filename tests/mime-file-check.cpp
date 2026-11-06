#include <QCoreApplication>
#include <QMimeDatabase>
#include <QTextStream>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream output(stdout);
    QMimeDatabase database;
    const bool names = app.arguments().contains(QStringLiteral("--names"));
    const bool families = app.arguments().contains(QStringLiteral("--families"));
    for (const auto &path : app.arguments().mid(1)) {
        if (path == QLatin1String("--families") || path == QLatin1String("--names")) continue;
        auto mime = names ? database.mimeTypeForName(path) : database.mimeTypeForFile(path);
        if (names && !mime.isValid()) {
            for (const auto &candidate : database.allMimeTypes()) {
                if (candidate.name().compare(path, Qt::CaseInsensitive) == 0) {
                    mime = candidate;
                    break;
                }
                for (const auto &alias : candidate.aliases()) {
                    if (alias.compare(path, Qt::CaseInsensitive) == 0) {
                        mime = candidate;
                        break;
                    }
                }
                if (mime.isValid()) break;
            }
        }
        output << path << '\t' << mime.name();
        if (families) output << '\t' << (mime.inherits(QStringLiteral("text/plain")) ? "text" : "");
        output << '\n';
    }
}
