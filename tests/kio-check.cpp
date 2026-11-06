#include <KIO/CopyJob>
#include <KIO/FileCopyJob>
#include <KIO/RestoreJob>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QTextStream>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout), err(stderr);
    QTemporaryDir dir(QDir::tempPath() + "/dolphin-kio-check-XXXXXX");
    if (!dir.isValid()) { err << "No se pudo crear el directorio temporal\n"; return 1; }
    const QString original = dir.filePath("original.txt");
    const QString copy = dir.filePath("copia.txt");
    const QString moved = dir.filePath("movido.txt");
    const QByteArray content("prueba KIO\n");
    QFile file(original);
    if (!file.open(QIODevice::WriteOnly) || file.write(content) != content.size()) return 1;
    file.close();
    auto run = [&](KJob *job, const char *name) {
        if (!job->exec()) { err << name << ": " << job->errorString() << '\n'; return false; }
        out << name << ": OK\n";
        return true;
    };
    if (!run(KIO::copy(QUrl::fromLocalFile(original), QUrl::fromLocalFile(copy), KIO::HideProgressInfo), "Copiar")) return 1;
    auto *conflict = KIO::file_copy(QUrl::fromLocalFile(original), QUrl::fromLocalFile(copy), -1, KIO::HideProgressInfo);
    if (conflict->exec()) { err << "El conflicto de nombres no fue rechazado\n"; return 1; }
    QFile existing(copy);
    if (!existing.open(QIODevice::ReadOnly) || existing.readAll() != content) {
        err << "El conflicto alteró el archivo existente\n"; return 1;
    }
    existing.close();
    out << "Conflicto de nombres rechazado: OK\n";
    if (!QDir().mkdir(dir.filePath("carpeta"))) return 1;
    QFile nested(dir.filePath("carpeta/interior.txt"));
    if (!nested.open(QIODevice::WriteOnly) || nested.write(content) != content.size()) return 1;
    nested.close();
    if (!run(KIO::copy(QUrl::fromLocalFile(dir.filePath("carpeta")), QUrl::fromLocalFile(dir.filePath("carpeta-copia")), KIO::HideProgressInfo), "Copiar carpeta")) return 1;
    QFile nestedCopy(dir.filePath("carpeta-copia/interior.txt"));
    if (!nestedCopy.open(QIODevice::ReadOnly) || nestedCopy.readAll() != content) {
        err << "El contenido de la carpeta copiada no coincide\n"; return 1;
    }
    if (!run(KIO::move(QUrl::fromLocalFile(copy), QUrl::fromLocalFile(moved), KIO::HideProgressInfo), "Mover")) return 1;
    QUrl trashUrl;
    auto *trash = KIO::trash(QUrl::fromLocalFile(moved), KIO::HideProgressInfo);
    QObject::connect(trash, &KIO::CopyJob::copyingDone, &app,
                     [&](KIO::Job *, const QUrl &, const QUrl &to, const QDateTime &, bool, bool) { trashUrl = to; });
    if (!run(trash, "Enviar a papelera")) return 1;
    if (!trashUrl.isValid() || trashUrl.scheme() != QLatin1String("trash")) {
        dir.setAutoRemove(false);
        err << "No se obtuvo la URL de papelera; carpeta conservada: " << dir.path() << '\n';
        return 1;
    }
    out << "URL de papelera KIO: " << trashUrl.toString() << '\n';
    if (!run(KIO::restoreFromTrash({trashUrl}, KIO::HideProgressInfo), "Restaurar")) {
        dir.setAutoRemove(false);
        err << "Archivo en " << trashUrl.toString() << "; carpeta conservada: " << dir.path() << '\n';
        return 1;
    }
    QFile restored(moved);
    if (!restored.open(QIODevice::ReadOnly) || restored.readAll() != content || QFile::exists(copy)) {
        dir.setAutoRemove(false);
        err << "Fallo al verificar contenido o ruta; carpeta conservada: " << dir.path() << '\n';
        return 1;
    }
    out << "Contenido y ruta restaurados: OK\n";
    return 0;
}
